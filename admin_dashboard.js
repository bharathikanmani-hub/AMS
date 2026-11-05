let attendanceData = {
    totalStudents: 0,
    present: 0,
    absent: 0,
    percentage: 0,
    today: [],
    students: [],
    records: [],
};

document.addEventListener("DOMContentLoaded", () => {
    requireRole("admin");
    setDate();
    setAdminProfile();
    loadAttendance();
});

function requireRole(role) {
    if (localStorage.getItem("userRole") !== role) {
        window.location.href = "index.html";
    }
}

function setAdminProfile() {
    const name = localStorage.getItem("userName") || "Administrator";
    const nameEl = document.getElementById("adminName");
    const initialEl = document.getElementById("adminInitial");
    if (nameEl) nameEl.textContent = name;
    if (initialEl) initialEl.textContent = name.charAt(0).toUpperCase();
}

function setDate() {
    const element = document.getElementById("todayDate");
    if (!element) return;
    element.textContent = new Date().toLocaleDateString("en-IN", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
    });
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

async function loadAttendance() {
    try {
        const response = await fetch("/api/attendance");
        attendanceData = await response.json();
        renderDashboard();
    } catch (error) {
        console.error(error);
    }
}

function renderDashboard() {
    setText("totalStudents", attendanceData.totalStudents);
    setText("presentStudents", attendanceData.present);
    setText("absentStudents", attendanceData.absent);
    setText("overallPercentage", `${attendanceData.percentage}%`);
    setText("recognitionPageMarked", attendanceData.present);
    setText("recognitionPageUnknown", attendanceData.absent);
    setText("recognitionPageRecognized", attendanceData.totalStudents);

    fillTable(
        "todayTable",
        attendanceData.today,
        (row) => `
            <tr>
                <td>${row.student_id}</td>
                <td>${statusBadge(row.status)}</td>
                <td>${row.time}</td>
            </tr>`
    );

    loadStudents(attendanceData.students);

    fillTable(
        "historyTable",
        [...attendanceData.records].reverse(),
        (row) => `
            <tr>
                <td>${row.date}</td>
                <td>${row.student_id}</td>
                <td>${statusBadge(row.status)}</td>
                <td>${row.time}</td>
            </tr>`
    );
}

function loadStudents(data) {
    fillTable(
        "studentTable",
        data,
        (student) => `
            <tr>
                <td>${student.id}</td>
                <td>${student.presentDays}</td>
                <td>${student.totalDays}</td>
                <td>${student.attendance}%</td>
                <td>${getStatus(student.attendance)}</td>
            </tr>`
    );
}

function fillTable(id, rows, renderRow) {
    const table = document.getElementById(id);
    if (!table) return;
    table.innerHTML = rows.length
        ? rows.map(renderRow).join("")
        : `<tr><td colspan="5">No records yet</td></tr>`;
}

function getStatus(attendance) {
    if (attendance >= 75) return `<span class="status safe">Safe</span>`;
    if (attendance >= 65) return `<span class="status warning">Warning</span>`;
    return `<span class="status critical">Low</span>`;
}

function statusBadge(status) {
    const kind = status === "Present" ? "safe" : "critical";
    return `<span class="status ${kind}">${status}</span>`;
}

function filterStudents() {
    const search = document.getElementById("studentSearch")?.value.toLowerCase() || "";
    loadStudents(
        attendanceData.students.filter((student) =>
            student.id.toLowerCase().includes(search)
        )
    );
}

function showSection(sectionId, button = null) {
    document.querySelectorAll(".section").forEach((section) => {
        section.classList.remove("active");
    });
    document.getElementById(sectionId)?.classList.add("active");
    document.querySelectorAll(".menu-btn").forEach((btn) => {
        btn.classList.remove("active");
    });
    if (button) button.classList.add("active");

    const titles = {
        dashboard: "Dashboard",
        students: "Students",
        attendance: "Attendance",
        recognition: "Face Attendance",
        reports: "Reports",
    };
    setText("pageTitle", titles[sectionId] || "Dashboard");
}

async function startRecognition() {
    const message = document.getElementById("recognitionMessage");
    try {
        const response = await fetch("/api/attendance/start", { method: "POST" });
        const data = await response.json();
        if (message) message.textContent = data.message;
        setTimeout(loadAttendance, 4000);
    } catch (error) {
        if (message) {
            message.textContent = "Could not start the camera. Start Flask first.";
        }
    }
}

function generateReport(type) {
    if (type === "daily") {
        const present = attendanceData.presentIds?.join(", ") || "None";
        const absent = attendanceData.absentIds?.join(", ") || "None";
        alert(`Today\nPresent: ${present}\nAbsent: ${absent}`);
        return;
    }

    if (type === "full") {
        alert(`${attendanceData.records.length} attendance rows saved.`);
        return;
    }

    const low = attendanceData.students.filter((student) => student.attendance < 75);
    alert(
        low.length
            ? low.map((student) => `${student.id}: ${student.attendance}%`).join("\n")
            : "No students below 75%."
    );
}

function logout() {
    localStorage.clear();
    window.location.href = "index.html";
}
