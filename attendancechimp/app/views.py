"""
views.py — HTTP request handlers for AttendanceChimp.

Each view corresponds to one URL endpoint.  Views receive an HTTP request,
interact with the database via models.py, and return an HTTP response.
"""

from django.shortcuts import render, redirect
from django.http import (HttpResponse, HttpResponseForbidden,
                         HttpResponseBadRequest, JsonResponse,HttpResponseNotAllowed)
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login
from datetime import datetime
from .models import InstructorProfile, StudentProfile,Course, Enrollment, Lecture, QRCodeUpload
import zoneinfo
import json
import io


# from .models import (InstructorProfile, StudentProfile, Course, Enrollment,
#                      Lecture, QRCodeUpload, is_instructor, is_student,
#                      getUploadsForCourse)

CDT = zoneinfo.ZoneInfo("America/Chicago")


# ---------------------------------------------------------------------------
# HW2  — index, time, sum
# ---------------------------------------------------------------------------

def time_view(request):
    current_time = datetime.now(CDT)
    return HttpResponse(
        current_time.strftime("%H:%M"),
        content_type="text/plain",
    )

def sum_view(request):
    n1 = float(request.GET["n1"])
    n2 = float(request.GET["n2"])
    return JsonResponse({"sum": n1 + n2})

def index(request):
    """Render the home page (index.html)."""
    current_time=datetime.now(CDT).strftime("%H:%M")
    context = {"current_time": current_time,"user": request.user}
    return render(request, 'app/index.html', context)



# ---------------------------------------------------------------------------
# HW4  — user creation
# ---------------------------------------------------------------------------

def new(request):
    if request.method!="GET":
        return HttpResponseNotAllowed(["GET"])
    return render(request, 'app/new.html')

@csrf_exempt
def createUser(request):
    if request.method!="POST":
        return HttpResponseNotAllowed(["POST"])
    user_name = request.POST.get("user_name","").strip()
    email = request.POST.get("email","").strip()
    password = request.POST.get("password","")
    is_student = request.POST.get("is_student","")
    if not user_name or not email or not password:
        return HttpResponseBadRequest("All fields are required.")
    if is_student not in ["0","1"]:
        return HttpResponseBadRequest("Choose student or instructor.")
    if User.objects.filter(email=email).count()>0:
        return HttpResponseBadRequest("Email already exists.")
    if User.objects.filter(username=user_name).count()>0:
        return HttpResponseBadRequest("Username already exists.")
    user = User.objects.create_user(username=user_name,email=email,password=password)
    if is_student=="1":
        StudentProfile.objects.create(user=user)
    else:
        InstructorProfile.objects.create(user=user)
    login(request,user)
    return HttpResponse("User created successfully.", status=200)
# ---------------------------------------------------------------------------
# HW5  — courses, lectures, QR uploads, dump
# ---------------------------------------------------------------------------

def new_course(request):
    if not request.user.is_authenticated:
        return HttpResponse("Please log in.", status=401)
    if InstructorProfile.objects.filter(user=request.user).count()==0:
        return HttpResponse("Instructors only.", status=401)
    if request.method!="GET":
        return HttpResponseNotAllowed(["GET"])
    return render(request, 'app/new_course.html')

def new_lecture(request):
    if not request.user.is_authenticated:
        return HttpResponse("Please log in.", status=401)
    if InstructorProfile.objects.filter(user=request.user).count()==0:
        return HttpResponse("Instructors only.", status=401)
    if request.method!="GET":
        return HttpResponseNotAllowed(["GET"])
    context={"courses": Course.objects.all()}
    return render(request, 'app/new_lecture.html', context)

def new_qr_upload(request):
    if not request.user.is_authenticated:
        return HttpResponse("Please log in.", status=401)
    if StudentProfile.objects.filter(user=request.user).count()==0:
        return HttpResponse("Students only.", status=401)
    if request.method!="GET":
        return HttpResponseNotAllowed(["GET"])
    return render(request, 'app/new_qr_upload.html')

@csrf_exempt
def createCourse(request):
    if not request.user.is_authenticated:
        return HttpResponse("Please log in.", status=401)

    instructors =  InstructorProfile.objects.filter(user=request.user)
    if instructors.count()==0:
        return HttpResponseForbidden("Instructors only.", status=401)
    if request.method!="POST":
        return HttpResponseNotAllowed(["POST"])

    course_name = request.POST.get("course-name","").strip()
    start_time = request.POST.get("start-time","").strip()
    end_time = request.POST.get("end-time","").strip()

    days=[]
    for day in ["mon","tue","wed","thu","fri"]:
        if "day-"+day in request.POST:
            days.append(day)

    if not course_name or not start_time or not end_time or len(days)==0:
        return HttpResponseBadRequest("Complete all fields and choose a day.")
    if Course.objects.filter(name=course_name).count()>0:
        return HttpResponseBadRequest("Course name already exists.")

    schedule=" ".join(days)+" "+start_time+"-"+end_time
    course=Course(name=course_name,instructor=instructors[0],meeting_schedule=schedule)
    course.save()
    return HttpResponse("Course created successfully.", status=200)

@csrf_exempt
def createLecture(request):
    if not request.user.is_authenticated:
        return HttpResponse("Please log in.", status=401)

    instructors =  InstructorProfile.objects.filter(user=request.user)
    if instructors.count()==0:
        return HttpResponseForbidden("Instructors only.", status=401)
    if request.method!="POST":
        return HttpResponseNotAllowed(["POST"])

    course_name = request.POST.get("choice","").strip()
    courses = Course.objects.filter(name=course_name)
    if courses.count()==0:
        return HttpResponseBadRequest("Choose an existing course.")

    lecture = Lecture(course=courses[0],date=datetime.now(CDT).date())
    lecture.save()
    return HttpResponse("Lecture created successfully.", status=200)

@csrf_exempt
def createQRCodeUpload(request):
    if not request.user.is_authenticated:
        return HttpResponse("Please log in.", status=401)

    students =  StudentProfile.objects.filter(user=request.user)
    if students.count()==0:
        return HttpResponseForbidden("Students only.", status=401)
    if request.method!="POST":
        return HttpResponseNotAllowed(["POST"])

    image = request.FILES.get("imageUpload")
    if image is None:
        return HttpResponseBadRequest("Choose an image.")

    upload = QRCodeUpload(student=students[0],image=image)
    upload.save()
    return HttpResponse("QR code uploaded successfully.", status=200)

def dumpUploads(request):
    if not request.user.is_authenticated:
        return HttpResponse("Please log in.", status=401)

    instructors =  InstructorProfile.objects.filter(user=request.user)
    if instructors.count()==0:
        return HttpResponseForbidden("Instructors only.", status=401)
    if request.method!="GET":
        return HttpResponseNotAllowed(["GET"])
    data = []
    for upload in QRCodeUpload.objects.all():
        data.append({"username": upload.student.user.username,"upload_time": upload.uploaded_at.strftime("%Y-%m-%d %H:%M:%S")})
    return JsonResponse(data, safe=False)
# ---------------------------------------------------------------------------
# HW6  — getUploads
# ---------------------------------------------------------------------------



