
# Claude: do step 5 of this document
"""
AttendanceChimp data model (LLM version).

Entities and relationships
--------------------------
    auth.User 1--1 InstructorProfile 1--* Course 1--* Lecture
    auth.User 1--1 StudentProfile
    StudentProfile *--* Course                  (through Enrollment)
    StudentProfile 1--* QRCodeUpload *--0..1 Lecture

Why two profile tables instead of one Users table?
    Django already handles authentication with auth.User. Data that belongs
    to only one role (a student ID, an instructor's department) goes in a
    separate profile table linked one-to-one to a User. This keeps foreign
    keys type-safe: a Course can only point at an InstructorProfile and an
    Enrollment can only point at a StudentProfile, so the database itself
    stops a student from "teaching" a course. One login can also hold both
    roles (for example, a TA who takes another class).

Anti-cheating measures
    * Each Lecture gets a random, unguessable qr_identifier instead of a
      sequential ID that a student could predict.
    * An upload is accepted only if the decoded QR value matches the
      lecture, the student is actively enrolled in that lecture's course,
      and the upload arrives during the lecture's check-in window.
    * A SHA-256 hash of each image is stored, so a byte-for-byte identical
      photo submitted by several students (one student photographs the code
      and shares the file) is detected.
    * A database constraint allows at most one accepted upload per student
      per lecture.
    * Rejected uploads are kept, with a reason, for instructor review.

Known limitation: the QR token is fixed for the whole lecture, so a student
in the room could send the token itself to an absent friend during the
window. Rotating tokens would close that gap but add complexity.
"""

import hashlib
import secrets
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# Single-letter weekday codes used in Course.meeting_days, indexed by
# date.weekday() (Monday == 0). "R" is Thursday and "U" is Sunday.
WEEKDAY_CODES = "MTWRFSU"

# How long before class starts / after class ends an upload still counts.
CHECKIN_OPENS_BEFORE = timedelta(minutes=10)
CHECKIN_CLOSES_AFTER = timedelta(minutes=0)


def generate_qr_token():
    """Return a random, URL-safe token (about 32 characters) for a QR code.

    Defined at module level, not as a lambda, so Django migrations can
    serialize it as a field default.
    """
    return secrets.token_urlsafe(24)


def _today():
    """Return today's date, whether or not the project uses time zones."""
    return timezone.localdate() if settings.USE_TZ else date.today()


class InstructorProfile(models.Model):
    """Instructor-specific data attached to a Django user.

    Fields:
        user:       the login account. One-to-one; deleting the user deletes
                    the profile. Courses use on_delete=PROTECT, so an
                    instructor who still teaches a course cannot be deleted.
        department: for example "Data Science".
        created_at: when the profile was created.

    Reverse relations:
        courses:    the Course objects this instructor teaches.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="instructor_profile",
    )
    department = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.get_username()


class StudentProfile(models.Model):
    """Student-specific data attached to a Django user.

    Fields:
        user:       the login account (one-to-one).
        student_id: the university ID number; unique.
        courses:    the courses the student is enrolled in, stored through
                    the Enrollment table.
        created_at: when the profile was created.

    Reverse relations:
        enrollments: Enrollment rows for this student.
        uploads:     QRCodeUpload rows submitted by this student.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    student_id = models.CharField(max_length=20, unique=True)
    courses = models.ManyToManyField(
        "Course",
        through="Enrollment",
        related_name="students",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        name = self.user.get_full_name() or self.user.get_username()
        return f"{name} ({self.student_id})"

    def is_enrolled_in(self, course):
        """Return True if this student has an active enrollment in course."""
        return self.enrollments.filter(course=course, is_active=True).exists()

    def attendance_rate(self, course, as_of=None):
        """Return the fraction (0.0 to 1.0) of lectures attended in course.

        Only lectures held on or before as_of (default: today) are counted.
        Returns 0.0 if no lectures have been held yet.
        """
        as_of = as_of or _today()
        lectures = course.lectures.filter(date__lte=as_of)
        total = lectures.count()
        if total == 0:
            return 0.0
        attended = (
            self.uploads.filter(
                status=QRCodeUpload.Status.ACCEPTED,
                lecture__in=lectures,
            )
            .values("lecture")
            .distinct()
            .count()
        )
        return attended / total


class Course(models.Model):
    """A course offering in a given term, taught by one instructor.

    Fields:
        code:         catalog code, for example "DATA 13600".
        name:         course title.
        term:         for example "Autumn 2026". (code, term) is unique.
        instructor:   the single instructor (PROTECT: an instructor cannot
                      be deleted while still assigned to a course).
        meeting_days: letters from "MTWRFSU", for example "MWF" or "TR".
        start_time:   daily start time of class meetings.
        end_time:     daily end time of class meetings.

    Reverse relations:
        students:    StudentProfile objects (through Enrollment).
        enrollments: Enrollment rows for this course.
        lectures:    Lecture objects for this course.
    """

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    term = models.CharField(max_length=20)
    instructor = models.ForeignKey(
        InstructorProfile,
        on_delete=models.PROTECT,
        related_name="courses",
    )
    meeting_days = models.CharField(
        max_length=7,
        help_text='Letters from "MTWRFSU", for example "MWF" or "TR".',
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["term", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["code", "term"],
                name="unique_course_code_per_term",
            ),
        ]

    def __str__(self):
        return f"{self.code}: {self.name} ({self.term})"

    def clean(self):
        """Validate the meeting schedule."""
        self.meeting_days = (self.meeting_days or "").upper()
        invalid = set(self.meeting_days) - set(WEEKDAY_CODES)
        if not self.meeting_days or invalid:
            raise ValidationError(
                {"meeting_days": 'Use only the letters "MTWRFSU", e.g. "MWF".'}
            )
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "End time must be after start time."})

    def meets_on(self, day):
        """Return True if the course is scheduled to meet on the given date."""
        return WEEKDAY_CODES[day.weekday()] in self.meeting_days.upper()

    def active_students(self):
        """Return the StudentProfile objects actively enrolled in this course."""
        return StudentProfile.objects.filter(
            enrollments__course=self,
            enrollments__is_active=True,
        )

    def attendance_summary(self):
        """Return this course's lectures, by date, annotated with num_present.

        num_present is the number of distinct students with an accepted
        upload for that lecture.
        """
        return self.lectures.annotate(
            num_present=models.Count(
                "uploads__student",
                filter=models.Q(uploads__status=QRCodeUpload.Status.ACCEPTED),
                distinct=True,
            )
        ).order_by("date")


class Enrollment(models.Model):
    """Join table linking students to courses (many-to-many).

    Fields:
        student:     the enrolled student.
        course:      the course.
        enrolled_at: when the enrollment was created.
        is_active:   False once the student drops. The row is kept so past
                     attendance stays explainable.

    A student can have at most one Enrollment row per course.
    """

    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"],
                name="unique_enrollment",
            ),
        ]

    def __str__(self):
        state = "active" if self.is_active else "dropped"
        return f"{self.student} in {self.course.code} ({state})"


class Lecture(models.Model):
    """A single class meeting of a course.

    Fields:
        course:        the course this lecture belongs to.
        date:          the date of the meeting. (course, date) is unique.
        topic:         optional description.
        qr_identifier: random token encoded in the QR code shown in class.
                       Unique and not editable in forms.
        created_at:    when the lecture row was created.

    The check-in window comes from the course's start_time and end_time on
    this date, widened by CHECKIN_OPENS_BEFORE and CHECKIN_CLOSES_AFTER.

    Reverse relations:
        uploads: QRCodeUpload rows matched to this lecture.
    """

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="lectures",
    )
    date = models.DateField()
    topic = models.CharField(max_length=200, blank=True)
    qr_identifier = models.CharField(
        max_length=64,
        unique=True,
        default=generate_qr_token,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["course", "date"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "date"],
                name="one_lecture_per_course_per_day",
            ),
        ]

    def __str__(self):
        return f"{self.course.code} on {self.date.isoformat()}"

    def _at(self, t):
        """Combine this lecture's date with time t into a datetime."""
        dt = datetime.combine(self.date, t)
        return timezone.make_aware(dt) if settings.USE_TZ else dt

    def checkin_window(self):
        """Return (opens, closes) datetimes during which uploads count."""
        opens = self._at(self.course.start_time) - CHECKIN_OPENS_BEFORE
        closes = self._at(self.course.end_time) + CHECKIN_CLOSES_AFTER
        return opens, closes

    def is_checkin_open(self, at=None):
        """Return True if the datetime at (default: now) is inside the window."""
        at = at or timezone.now()
        opens, closes = self.checkin_window()
        return opens <= at <= closes

    def attendees(self):
        """Return the students with an accepted upload for this lecture."""
        return StudentProfile.objects.filter(
            uploads__lecture=self,
            uploads__status=QRCodeUpload.Status.ACCEPTED,
        ).distinct()

    def attendance_count(self):
        """Return the number of students marked present for this lecture."""
        return self.attendees().count()

    def regenerate_qr_identifier(self):
        """Issue a new QR token (for example if the old one leaked) and save it."""
        self.qr_identifier = generate_qr_token()
        self.save(update_fields=["qr_identifier"])


class QRCodeUpload(models.Model):
    """A photo of a lecture's QR code uploaded by a student.

    Fields:
        student:          who uploaded it.
        lecture:          the matched lecture. Optional: it may be unknown at
                          upload time and filled in by evaluate() from the
                          decoded QR value. SET_NULL keeps the record if the
                          lecture is deleted.
        image:            the uploaded photo. A FileField is used so the model
                          does not depend on Pillow.
        image_sha256:     hash of the image bytes, used to spot one photo
                          shared between students.
        decoded_value:    text read from the QR code by the upload view.
        uploaded_at:      server-side timestamp, not editable by the client.
        client_ip:        optional IP address of the uploader, for audits.
        status:           pending / accepted / rejected.
        rejection_reason: why an upload was rejected (blank otherwise).

    At most one accepted upload per (student, lecture) is allowed by a
    database constraint, so attendance cannot be double counted.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="uploads",
    )
    lecture = models.ForeignKey(
        Lecture,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploads",
    )
    image = models.FileField(upload_to="qr_uploads/%Y/%m/%d/")
    image_sha256 = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        editable=False,
    )
    decoded_value = models.CharField(
        max_length=255,
        blank=True,
        help_text="Text decoded from the QR code in the photo.",
    )
    uploaded_at = models.DateTimeField(default=timezone.now, editable=False)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    rejection_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "lecture"],
                condition=models.Q(status="accepted"),
                name="one_accepted_upload_per_student_per_lecture",
            ),
        ]

    def __str__(self):
        target = self.lecture if self.lecture is not None else "unmatched lecture"
        return f"{self.student} -> {target} [{self.status}]"

    @property
    def is_accepted(self):
        """True if this upload counts as attendance."""
        return self.status == self.Status.ACCEPTED

    def compute_image_hash(self):
        """Return the SHA-256 hex digest of the uploaded image bytes."""
        digest = hashlib.sha256()
        for chunk in self.image.chunks():
            digest.update(chunk)
        return digest.hexdigest()

    def save(self, *args, **kwargs):
        if self.image and not self.image_sha256:
            self.image_sha256 = self.compute_image_hash()
        super().save(*args, **kwargs)

    def _reject(self, reason):
        self.status = self.Status.REJECTED
        self.rejection_reason = reason
        return self.status

    def evaluate(self):
        """Decide whether this upload counts as attendance.

        Sets status and rejection_reason but does not save; the caller
        should call save() afterwards. Expects decoded_value to have been
        filled in by the view that decodes the QR code.

        Checks, in order:
            1. a QR value was decoded from the image;
            2. it matches a lecture (if lecture is empty, the lecture is
               looked up by qr_identifier);
            3. the student is actively enrolled in that lecture's course;
            4. uploaded_at falls inside the lecture's check-in window;
            5. no other student already submitted an identical image for
               this lecture;
            6. the student does not already have an accepted upload for it.

        Returns the resulting status.
        """
        if self.image and not self.image_sha256:
            self.image_sha256 = self.compute_image_hash()

        if not self.decoded_value:
            return self._reject("No QR code could be read from the image.")

        if self.lecture is None:
            self.lecture = Lecture.objects.filter(
                qr_identifier=self.decoded_value
            ).first()
            if self.lecture is None:
                return self._reject("QR code does not match any lecture.")
        elif self.decoded_value != self.lecture.qr_identifier:
            return self._reject("QR code does not match the selected lecture.")

        if not self.student.is_enrolled_in(self.lecture.course):
            return self._reject("Student is not enrolled in this course.")

        if not self.lecture.is_checkin_open(self.uploaded_at):
            return self._reject("Uploaded outside the lecture's check-in window.")

        others = QRCodeUpload.objects.filter(lecture=self.lecture).exclude(pk=self.pk)
        if (
            self.image_sha256
            and others.filter(image_sha256=self.image_sha256)
            .exclude(student=self.student)
            .exists()
        ):
            return self._reject(
                "An identical image was already submitted by another student."
            )

        if others.filter(student=self.student, status=self.Status.ACCEPTED).exists():
            return self._reject("Attendance is already recorded for this lecture.")

        self.status = self.Status.ACCEPTED
        self.rejection_reason = ""
        return self.status
