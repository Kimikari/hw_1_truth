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
from .models import InstructorProfile, StudentProfile
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



# ---------------------------------------------------------------------------
# HW6  — getUploads
# ---------------------------------------------------------------------------



