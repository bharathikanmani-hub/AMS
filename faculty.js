
const students = [
    ["22CSE001", "Aishwarya S", "Present", "-"],
    ["22CSE002", "Bharath S", "Present", "-"],
    ["22CSE003", "Divya P", "Present", "-"],
    ["22CSE004", "Gayathri R", "Absent", "Sick leave"],
    ["22CSE005", "Harish V", "Present", "-"],
    ["22CSE006", "Janani K", "Absent", "Network issue"],
    ["22CSE007", "Karthik M", "Present", "-"],
    ["22CSE008", "Monisha T", "Present", "-"],
    ["22CSE009", "Naveen K", "Absent", "-"],
    ["22CSE010", "Priya D", "Present", "-"],
    ["22CSE011", "Ragavi S", "Present", "-"],
    ["22CSE012", "Santhosh P", "Absent", "Medical Leave"],
    ["22CSE013", "Sneha M", "Present", "-"],
    ["22CSE014", "Surya K", "Present", "-"],
    ["22CSE015", "Varun R", "Absent", "-"],
    ["22CSE016", "Vidhya P", "Present", "-"],
    ["22CSE017", "Yogesh S", "Present", "-"],
    ["22CSE018", "Abinaya R", "Present", "-"],
    ["22CSE019", "Akash M", "Absent", "-"],
    ["22CSE020", "Anitha S", "Present", "-"],
    ["22CSE021", "Arun P", "Present", "-"],
    ["22CSE022", "Bala K", "Present", "-"],
    ["22CSE023", "Deepa R", "Absent", "-"],
    ["22CSE024", "Dinesh V", "Present", "-"],
    ["22CSE025", "Gokul S", "Present", "-"],
    ["22CSE026", "Hema P", "Present", "-"],
    ["22CSE027", "Irfan A", "Absent", "-"],
    ["22CSE028", "Keerthana M", "Present", "-"],
    ["22CSE029", "Lokesh T", "Present", "-"],
    ["22CSE030", "Meena S", "Present", "-"],
    ["22CSE031", "Nandha R", "Absent", "-"],
    ["22CSE032", "Pavithra K", "Present", "-"],
    ["22CSE033", "Praveen S", "Present", "-"],
    ["22CSE034", "Ramya P", "Present", "-"],
    ["22CSE035", "Sanjay M", "Absent", "-"],
    ["22CSE036", "Shalini R", "Present", "-"],
    ["22CSE037", "Siva K", "Present", "-"],
    ["22CSE038", "Tharani S", "Present", "-"],
    ["22CSE039", "Vasanth P", "Absent", "-"],
    ["22CSE040", "Yamini R", "Present", "-"],
    ["22CSE041", "Zara F", "Present", "-"],
    ["22CSE042", "Mohan V", "Present", "-"]
];

const pageSize = 12;
let currentPage = 1;
let showAllAlerts = false;
let savedSnapshot = students.map(student => [...student]);

// SET DEFAULT DATE
document.getElementById("attendanceDate").value =
    new Date().toISOString().slice(0, 10);

// PREVENT HTML INJECTION WHEN DISPLAYING TEXT
function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, function (character) {
        return {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        }[character];
    });
}

// DISPLAY STUDENT TABLE
function displayStudents() {
    const tbody = document.getElementById("studentRows");
    tbody.innerHTML = "";

    const start = (currentPage - 1) * pageSize;
    const visibleStudents = students.slice(start, start + pageSize);

    visibleStudents.forEach(function (student, position) {
        const index = start + position;
        const isPresent = student[2] === "Present";
        const row = document.createElement("tr");

        row.innerHTML = `
            <td>
                <input type="checkbox"
                    class="student-check"
                    data-index="${index}">
            </td>

            <td>${escapeHTML(student[0])}</td>

            <td>${escapeHTML(student[1])}</td>

            <td>
                <span class="status ${isPresent ? "present" : "absent"}">
                    ${isPresent ? "✓ Present" : "✕ Absent"}
                </span>
            </td>

            <td>
                <input class="remark"
                    data-remark="${index}"
                    value="${escapeHTML(student[3])}">
            </td>

            <td>
                <div class="actions">
                    <button
                        class="${!isPresent ? "set-present" : ""}"
                        data-status="Present"
                        data-index="${index}">
                        ✓ Mark Present
                    </button>

                    <button
                        class="${isPresent ? "set-absent" : ""}"
                        data-status="Absent"
                        data-index="${index}">
                        ✕ Mark Absent
                    </button>
                </div>
            </td>
        `;

        tbody.appendChild(row);
    });

    // MARK INDIVIDUAL STUDENT PRESENT OR ABSENT
    tbody.querySelectorAll("[data-status]").forEach(function (button) {
        button.addEventListener("click", function () {
            const index = Number(button.dataset.index);
            students[index][2] = button.dataset.status;
            renderAll();
        });
    });

    // UPDATE REMARKS
    tbody.querySelectorAll("[data-remark]").forEach(function (input) {
        input.addEventListener("change", function () {
            const index = Number(input.dataset.remark);
            students[index][3] = input.value.trim() || "-";
        });
    });

    document.getElementById("showingText").textContent =
        `Showing ${start + 1} to ${
            Math.min(start + pageSize, students.length)
        } of ${students.length} students`;

    displayPagination();
}

// PAGINATION
function displayPagination() {
    const container = document.getElementById("pagination");
    container.innerHTML = "";

    const totalPages = Math.ceil(students.length / pageSize);

    function addPage(label, page, active) {
        const button = document.createElement("button");
        button.textContent = label;

        if (active) {
            button.className = "active";
        }

        button.disabled = page < 1 || page > totalPages;

        button.addEventListener("click", function () {
            currentPage = page;
            displayStudents();
        });

        container.appendChild(button);
    }

    addPage("‹", currentPage - 1, false);

    for (let page = 1; page <= totalPages; page++) {
        addPage(page, page, page === currentPage);
    }

    addPage("›", currentPage + 1, false);
}

// UPDATE ATTENDANCE COUNTS AND CHART
function displaySummary() {
    const total = students.length;

    const present = students.filter(function (student) {
        return student[2] === "Present";
    }).length;

    const absent = total - present;

    const presentPercentage =
        total ? (present / total) * 100 : 0;

    const absentPercentage =
        total ? (absent / total) * 100 : 0;

    const percentageText = presentPercentage.toFixed(1) + "%";

    document.getElementById("total").textContent = total;
    document.getElementById("present").textContent = present;
    document.getElementById("absent").textContent = absent;

    document.getElementById("presentPct").textContent =
        percentageText;

    document.getElementById("absentPct").textContent =
        absentPercentage.toFixed(1) + "%";

    document.getElementById("todayPct").textContent =
        percentageText;

    document.getElementById("donutPercent").textContent =
        percentageText;

    document.getElementById("legendPresent").textContent = present;
    document.getElementById("legendAbsent").textContent = absent;
    document.getElementById("legendTotal").textContent = total;

    document.getElementById("donut").style.background =
        `conic-gradient(
            #13b981 0 ${presentPercentage}%,
            #dbe7f5 ${presentPercentage}% 100%
        )`;
}

// LOW ATTENDANCE / ABSENT STUDENT ALERTS
function displayAlerts() {
    const container = document.getElementById("alertsList");
    container.innerHTML = "";

    const absentStudents = students.filter(function (student) {
        return student[2] === "Absent";
    });

    const list = showAllAlerts
        ? absentStudents
        : absentStudents.slice(0, 4);

    if (list.length === 0) {
        container.innerHTML = "<p>No absent students right now.</p>";
        return;
    }

    list.forEach(function (student) {
        const initials = student[1]
            .split(" ")
            .map(function (part) {
                return part[0];
            })
            .join("")
            .slice(0, 2);

        const item = document.createElement("div");
        item.className = "alert-row";

        item.innerHTML = `
            <div class="initials">${escapeHTML(initials)}</div>

            <div class="alert-name">
                <strong>${escapeHTML(student[1])}</strong>
                <small>${escapeHTML(student[0])}</small>
            </div>

            <strong>Absent</strong>
            <span class="tag">Review</span>
        `;

        container.appendChild(item);
    });
}

// UPDATE ALL DASHBOARD SECTIONS
function renderAll() {
    displayStudents();
    displaySummary();
    displayAlerts();

    document.getElementById("selectAll").checked = false;
}

// SELECT ALL STUDENTS ON CURRENT PAGE
document.getElementById("selectAll").addEventListener(
    "change",
    function (event) {
        document.querySelectorAll(".student-check").forEach(
            function (checkbox) {
                checkbox.checked = event.target.checked;
            }
        );
    }
);

// MARK SELECTED STUDENTS OR EVERYONE
function markStudents(status) {
    const selected = [
        ...document.querySelectorAll(".student-check:checked")
    ];

    if (selected.length > 0) {
        selected.forEach(function (checkbox) {
            students[Number(checkbox.dataset.index)][2] = status;
        });
    } else {
        students.forEach(function (student) {
            student[2] = status;
        });
    }

    renderAll();
}

document.getElementById("allPresent").addEventListener(
    "click",
    function () {
        markStudents("Present");
    }
);

document.getElementById("allAbsent").addEventListener(
    "click",
    function () {
        markStudents("Absent");
    }
);

// RESET UNSAVED CHANGES
document.getElementById("resetBtn").addEventListener(
    "click",
    function () {
        students.forEach(function (student, index) {
            students[index] = [...savedSnapshot[index]];
        });

        currentPage = 1;

        document.getElementById("saveMessage").textContent =
            "Unsaved changes have been reset.";

        renderAll();
    }
);

// SAVE CURRENT VERSION IN BROWSER MEMORY
document.getElementById("saveBtn").addEventListener(
    "click",
    function () {
        savedSnapshot = students.map(student => [...student]);

        document.getElementById("saveMessage").textContent =
            "Attendance updated in this browser session. " +
            "Connect Flask and your database to save permanently.";
    }
);

// SHOW ALL ALERTS
document.getElementById("viewAlerts").addEventListener(
    "click",
    function () {
        showAllAlerts = !showAllAlerts;

        document.getElementById("viewAlerts").textContent =
            showAllAlerts ? "Show Less" : "View All";

        displayAlerts();
    }
);

// DOWNLOAD ATTENDANCE AS CSV
document.getElementById("downloadReport").addEventListener(
    "click",
    function () {
        const data = [
            ["Roll No", "Student Name", "Status", "Remarks"],
            ...students
        ];

        const csv = data.map(function (row) {
            return row.map(function (value) {
                return '"' + String(value).replace(/"/g, '""') + '"';
            }).join(",");
        }).join("\r\n");

        const blob = new Blob(
            [csv],
            { type: "text/csv;charset=utf-8;" }
        );

        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");

        link.href = url;
        link.download = "class_attendance.csv";
        link.click();

        URL.revokeObjectURL(url);
    }
);

// START DASHBOARD
renderAll();
