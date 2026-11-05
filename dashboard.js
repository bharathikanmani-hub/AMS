document.addEventListener("DOMContentLoaded", () => {
    const page = document.title;
    if (page.includes("Faculty")) {
        requireRole("faculty");
        fillProfile();
        loadToday();
    } else if (page.includes("Student")) {
        requireRole("student");
        fillProfile();
        const savedId = localStorage.getItem("studentId");
        const input = document.getElementById("studentIdInput");
        if (savedId && input) {
            input.value = savedId;
            loadStudentAttendance();
        }
    }
});

function requireRole(role) {
    if (localStorage.getItem("userRole") !== role) {
        window.location.href = "index.html";
    }
}

function fillProfile() {
    const name = localStorage.getItem("userName") || "User";
    const nameEl = document.getElementById("userName");
    const initialEl = document.getElementById("userInitial");
    if (nameEl) nameEl.textContent = name;
    if (initialEl) initialEl.textContent = name.charAt(0).toUpperCase();
}

function showSection(sectionId, button) {
    document.querySelectorAll(".section").forEach((section) => {
        section.classList.remove("active");
    });
    document.getElementById(sectionId)?.classList.add("active");
    document.querySelectorAll(".menu-btn").forEach((btn) => {
        btn.classList.remove("active");
    });
    if (button) button.classList.add("active");
    const titles = {
        session: "Take attendance",
        today: "Today's class",
    };
    const title = document.getElementById("pageTitle");
    if (title) title.textContent = titles[sectionId] || title.textContent;
}

async function loadToday() {
    try {
        const response = await fetch("/api/attendance");
        const data = await response.json();
        const present = document.getElementById("presentCount");
        const absent = document.getElementById("absentCount");
        if (present) present.textContent = data.present;
        if (absent) absent.textContent = data.absent;

        const table = document.getElementById("todayTable");
        if (table) {
            table.innerHTML = data.today.length
                ? data.today
                      .map(
                          (row) => `
                    <tr>
                        <td>${row.student_id}</td>
                        <td>${row.status}</td>
                        <td>${row.time}</td>
                    </tr>`
                      )
                      .join("")
                : `<tr><td colspan="3">No attendance taken yet today</td></tr>`;
        }
    } catch (error) {
        console.error(error);
    }
}

async function startRecognition() {
    const message = document.getElementById("sessionMessage");
    try {
        const response = await fetch("/api/attendance/start", { method: "POST" });
        const data = await response.json();
        if (message) message.textContent = data.message;
        setTimeout(loadToday, 4000);
    } catch (error) {
        if (message) {
            message.textContent = "Could not start the camera. Keep Flask running.";
        }
    }
}

async function loadStudentAttendance() {
    const input = document.getElementById("studentIdInput");
    const studentId = input?.value.trim();
    if (!studentId) return;

    localStorage.setItem("studentId", studentId);

    try {
        const response = await fetch(
            `/api/attendance?studentId=${encodeURIComponent(studentId)}`
        );
        const data = await response.json();
        const stats = data.students[0];
        document.getElementById("presentDays").textContent = stats
            ? stats.presentDays
            : 0;
        document.getElementById("attendancePercent").textContent = stats
            ? `${stats.attendance}%`
            : "0%";

        const table = document.getElementById("studentHistory");
        table.innerHTML = data.records.length
            ? data.records
                  .slice()
                  .reverse()
                  .map(
                      (row) => `
                <tr>
                    <td>${row.date}</td>
                    <td>${row.status}</td>
                    <td>${row.time}</td>
                </tr>`
                  )
                  .join("")
            : `<tr><td colspan="3">No records for this Student ID</td></tr>`;
    } catch (error) {
        console.error(error);
    }
}

function logout() {
    localStorage.clear();
    window.location.href = "index.html";
}
