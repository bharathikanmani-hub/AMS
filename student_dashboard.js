
/* SAMPLE DASHBOARD DATA
   Replace this sample data with Flask API data when integrating MySQL.
*/

const student = {
    name: "Priya S",
    registerNumber: "22CS101"
};

const subjects = [
    { name: "Data Structures & Algorithms", percent: 92, color: "#2583f8" },
    { name: "Database Management System", percent: 88, color: "#13b981" },
    { name: "Computer Networks", percent: 70, color: "#8054e8" },
    { name: "Operating Systems", percent: 68, color: "#ff9f1c" },
    { name: "Web Technologies", percent: 62, color: "#06b6d4" }
];

const attendanceRecords = [
    { date: "14 Oct 2025", subject: "Database Management Systems", status: "Present", mode: "Face" },
    { date: "13 Oct 2025", subject: "Computer Networks", status: "Present", mode: "Face" },
    { date: "10 Oct 2025", subject: "Operating Systems", status: "Present", mode: "Face" },
    { date: "09 Oct 2025", subject: "Data Structures & Algorithms", status: "Absent", mode: "-" },
    { date: "08 Oct 2025", subject: "Web Technologies", status: "Present", mode: "Face" },
    { date: "07 Oct 2025", subject: "Computer Networks", status: "Present", mode: "Face" }
];

const timetable = [
    { day: "Monday", subject: "Data Structures & Algorithms", time: "09:00 - 10:00", room: "A101" },
    { day: "Tuesday", subject: "Database Management Systems", time: "10:00 - 11:00", room: "A102" },
    { day: "Wednesday", subject: "Computer Networks", time: "09:00 - 10:00", room: "B201" },
    { day: "Thursday", subject: "Operating Systems", time: "11:00 - 12:00", room: "B202" },
    { day: "Friday", subject: "Web Technologies", time: "10:00 - 11:00", room: "A103" },
    { day: "Saturday", subject: "Data Structures & Algorithms", time: "09:00 - 10:00", room: "A101" }
];

const overallPresent = 43;
const overallAbsent = 7;
const overallTotal = overallPresent + overallAbsent;
const overallPercent = Math.round((overallPresent / overallTotal) * 100);

let showAllAttendance = false;
let showAllTimetable = false;
let showAllLowAttendance = false;

/* INITIALIZE DASHBOARD */

document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("currentDate").textContent =
        new Date().toLocaleDateString("en-IN", {
            weekday: "short",
            day: "2-digit",
            month: "short",
            year: "numeric"
        });

    document.getElementById("userName").textContent = student.name;
    document.getElementById("profileName").textContent = student.name;
    document.getElementById("registerNumber").textContent =
        student.registerNumber;

    document.getElementById("userInitial").textContent =
        student.name.charAt(0).toUpperCase();

    document.getElementById("profileInitial").textContent =
        student.name.charAt(0).toUpperCase();

    document.getElementById("presentCount").textContent = overallPresent;
    document.getElementById("absentCount").textContent = overallAbsent;
    document.getElementById("totalCount").textContent = overallTotal;

    document.getElementById("attendancePercent").textContent =
        overallPercent + "%";

    document.getElementById("attendanceCircle").style.setProperty(
        "--percentage", overallPercent
    );

    const message = document.getElementById("attendanceMessage");

    if (overallPercent < 75) {
        message.textContent =
            "⚠ Your overall attendance is below 75%.";
        message.style.background = "#fff0f1";
        message.style.color = "#c52b3a";
    } else {
        message.textContent =
            "✓ Good! Your attendance is above 75%.";
    }

    displaySubjects(subjects);
    displayAttendance(attendanceRecords);
    displayTimetable(timetable);
    displayAlerts(subjects);

    document.getElementById("searchInput").addEventListener(
        "input", filterSubjects
    );

    document.querySelectorAll(".menu-btn[href]").forEach(function (link) {
        link.addEventListener("click", function () {
            document.querySelectorAll(".menu-btn").forEach(function (btn) {
                btn.classList.remove("active");
            });

            link.classList.add("active");
        });
    });
});

/* SUBJECT-WISE ATTENDANCE */

function displaySubjects(data) {
    const container = document.getElementById("subjectList");
    container.innerHTML = "";

    if (data.length === 0) {
        container.innerHTML = "<p>No matching subjects found.</p>";
        return;
    }

    data.forEach(function (subject) {
        const row = document.createElement("div");
        row.className = "subject-row";

        const info = document.createElement("div");
        info.className = "subject-info";

        const name = document.createElement("span");
        name.textContent = subject.name;

        const percentage = document.createElement("strong");
        percentage.textContent = subject.percent + "%";

        info.appendChild(name);
        info.appendChild(percentage);

        const track = document.createElement("div");
        track.className = "progress-track";

        const fill = document.createElement("div");
        fill.className = "progress-fill";
        fill.style.width = Math.max(0, Math.min(100, subject.percent)) + "%";
        fill.style.background = subject.color;

        track.appendChild(fill);
        row.appendChild(info);
        row.appendChild(track);
        container.appendChild(row);
    });
}

/* SEARCH SUBJECTS */

function filterSubjects() {
    const search = document.getElementById("searchInput")
        .value.toLowerCase().trim();

    const filtered = subjects.filter(function (subject) {
        return subject.name.toLowerCase().includes(search);
    });

    displaySubjects(filtered);
}

/* RECENT ATTENDANCE RECORDS */

function displayAttendance(data) {
    const tbody = document.getElementById("studentHistory");
    tbody.innerHTML = "";

    const recordsToShow = showAllAttendance ? data : data.slice(0, 6);

    if (recordsToShow.length === 0) {
        tbody.innerHTML =
            '<tr><td colspan="4">No attendance records found.</td></tr>';
        return;
    }

    recordsToShow.forEach(function (record) {
        const tr = document.createElement("tr");

        const date = document.createElement("td");
        date.textContent = record.date;

        const subject = document.createElement("td");
        subject.textContent = record.subject;

        const statusCell = document.createElement("td");
        const status = document.createElement("span");

        status.className = "status " +
            (record.status === "Present" ? "present" : "absent");

        status.textContent = record.status;
        statusCell.appendChild(status);

        const mode = document.createElement("td");
        mode.textContent = record.mode;

        tr.appendChild(date);
        tr.appendChild(subject);
        tr.appendChild(statusCell);
        tr.appendChild(mode);

        tbody.appendChild(tr);
    });
}

function showAllRecords() {
    showAllAttendance = !showAllAttendance;
    displayAttendance(attendanceRecords);

    document.querySelector(".records-card .text-btn").textContent =
        showAllAttendance ? "Show Less" : "View All";
}

/* WEEKLY TIMETABLE */

function displayTimetable(data) {
    const tbody = document.getElementById("timetableBody");
    tbody.innerHTML = "";

    const rows = showAllTimetable ? data : data.slice(0, 6);

    rows.forEach(function (item) {
        const tr = document.createElement("tr");

        const dayCell = document.createElement("td");
        const badge = document.createElement("span");
        badge.className = "day-badge";
        badge.textContent = item.day;
        dayCell.appendChild(badge);

        const subjectCell = document.createElement("td");
        subjectCell.textContent = item.subject;

        const timeCell = document.createElement("td");
        timeCell.textContent = item.time;

        const roomCell = document.createElement("td");
        roomCell.textContent = item.room;

        tr.appendChild(dayCell);
        tr.appendChild(subjectCell);
        tr.appendChild(timeCell);
        tr.appendChild(roomCell);

        tbody.appendChild(tr);
    });
}

function showFullTimetable() {
    showAllTimetable = !showAllTimetable;
    displayTimetable(timetable);

    document.querySelector(".timetable-card .text-btn").textContent =
        showAllTimetable ? "Show Less" : "View Full Time Table";
}

/* LOW ATTENDANCE ALERTS */

function displayAlerts(data) {
    const container = document.getElementById("alertList");
    container.innerHTML = "";

    const lowSubjects = data.filter(function (subject) {
        return subject.percent < 75;
    });

    const alerts = showAllLowAttendance
        ? lowSubjects
        : lowSubjects.slice(0, 3);

    if (alerts.length === 0) {
        container.innerHTML =
            "<p>All subjects have attendance of 75% or above.</p>";
    }

    alerts.forEach(function (subject) {
        const item = document.createElement("div");
        item.className = "alert-item";

        const details = document.createElement("div");

        const name = document.createElement("strong");
        name.textContent = subject.name;

        const description = document.createElement("p");
        description.textContent = "Attendance is below 75%";

        details.appendChild(name);
        details.appendChild(description);

        const percent = document.createElement("span");
        percent.className = "alert-percent";
        percent.textContent = subject.percent + "%";

        item.appendChild(details);
        item.appendChild(percent);
        container.appendChild(item);
    });

    const warning = document.getElementById("warningText");

    if (lowSubjects.length > 0) {
        warning.textContent =
            "Your attendance in " + lowSubjects.length +
            " subject(s) is below 75%. Attend upcoming classes regularly.";
    } else {
        warning.textContent =
            "Great! All your subjects have attendance of at least 75%.";
    }
}

function showAllAlerts() {
    showAllLowAttendance = !showAllLowAttendance;
    displayAlerts(subjects);

    document.querySelector(".alerts-card .text-btn").textContent =
        showAllLowAttendance ? "Show Less" : "View All";
}

/* LOGOUT */

function logout() {
    if (confirm("Are you sure you want to logout?")) {
        window.location.href = "/logout";
    }
}
