"""
models.py — Data model for AttendanceChimp.

AttendanceChimp is an electronic class attendance tool.  Instructors create
courses and lectures; each lecture is assigned a random QR code.  Students
photograph the QR code and upload the image.  The system decodes the QR code,
matches it to a lecture, and records the attendance.

Entities
--------
- InstructorProfile: extends Django User → instructor-specific data
- StudentProfile  : extends Django User → student-specific data
- Course          : a course taught by one instructor
- Enrollment      : junction table linking students to courses
- Lecture         : a single class meeting (has a QR-code identifier)
- QRCodeUpload    : a student's uploaded QR-code photograph
"""

from django.db import models
from django.contrib.auth.models import User
from datetime import datetime
import zoneinfo

import logging
import string
import random

logger = logging.getLogger(__name__) # set up tracking, auditing, and debugging
                                                               # allows using logger.warning(), logger.error(), 
                                                               # logger.info(), etc. Better than print() for debuggin... 


# ---------------------------------------------------------------------------
# User profiles
# ---------------------------------------------------------------------------

class InstructorProfile(models.Model):
    """connects each instructor profile to a Django user account, deleted if the account is deleted"""
    user = models.OneToOneField(User, on_delete=models.CASCADE)

class StudentProfile(models.Model):
    """connects each student profile to a Django user account, deleted if the account is deleted"""
    user = models.OneToOneField(User, on_delete=models.CASCADE)

# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------
class Course(models.Model):
    """stores the course's name, schedule and instructor"""
    name = models.CharField(max_length=200)
    instructor = models.ForeignKey(InstructorProfile, on_delete=models.CASCADE)
    meeting_schedule = models.CharField(max_length=200)

    course=models.CharField(max_length=200, null=True)
    start_time=models.TimeField(max_length=5, null=True)
    end_time=models.TimeField(max_length=5, null=True)
    day_mon=models.BooleanField(default=False)
    day_tue=models.BooleanField(default=False)
    day_wed=models.BooleanField(default=False)
    day_thu=models.BooleanField(default=False) 
    day_fri=models.BooleanField(default=False)

    def meets_on_day(self, day):
        days=[self.day_mon, self.day_tue, self.day_wed, self.day_thu, self.day_fri]
        return days[day]
    


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

class Enrollment(models.Model):
    """connects one student to one course"""
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)



# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
def generate_qr_code():
    """generate a random 32 character qr code"""
    return "".join(
        random.SystemRandom().choices(
            string.ascii_letters + string.digits, k=32
        )
    )

class Lecture(models.Model):
    """stores course, date, and qr code"""

    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    date = models.DateField()
    qr_code = models.CharField(max_length=100,unique=True,default=generate_qr_code,)


# ---------------------------------------------------------------------------
# QR Code Upload
# ---------------------------------------------------------------------------


class QRCodeUpload(models.Model):
    """stores qr code image and the upload time"""

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE)
    lecture = models.ForeignKey(Lecture, on_delete=models.SET_NULL, null=True, blank=True,)
    image = models.FileField(upload_to="qr_uploads/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

# ---------------------------------------------------------------------------
# Helper / API functions
# ---------------------------------------------------------------------------
def getUploadsForCourse(course):
    courses=Course.objects.filter(course=course)
    if courses.count() == 0:
        return []

    course_object=courses[0]
    if not course_object.start_time or not course_object.end_time:
        return []

    start=course_object.start_time
    end=course_object.end_time
    chicago=zoneinfo.ZoneInfo("America/Chicago")
    valid_uploads=[]
    for upload in QRCodeUpload.objects.filter(lecture__course=course_object):
        local_timestamp=upload.uploaded_at.astimezone(chicago)
        if course_object.meets_on_day(local_timestamp.weekday()):
            if start <= local_timestamp.time() <= end:
                valid_uploads.append(upload)

    return valid_uploads