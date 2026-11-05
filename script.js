// ==========================================
// AI CLASSROOM ATTENDANCE SYSTEM
// script.js
// ==========================================


// ==========================================
// ELEMENTS
// ==========================================

const roleButtons = document.querySelectorAll(".role-button");

const roleInput = document.getElementById("role");

const loginForm = document.getElementById("loginForm");
const signupForm = document.getElementById("signupForm");

const loginView = document.getElementById("loginView");
const signupView = document.getElementById("signupView");

const showSignupButton = document.getElementById("showSignup");
const showLoginButton = document.getElementById("showLogin");

const passwordInput = document.getElementById("password");
const togglePassword = document.getElementById("togglePassword");

const loginMessage = document.getElementById("message");
const signupMessage = document.getElementById("signupMessage");


// ==========================================
// ROLE SELECTION - SIGN IN
// ==========================================

roleButtons.forEach((button) => {

    button.addEventListener("click", () => {

        // Remove active from all buttons
        roleButtons.forEach((item) => {
            item.classList.remove("active");
        });

        // Add active to selected button
        button.classList.add("active");

        // Store selected role
        roleInput.value = button.dataset.role;

    });

});


// ==========================================
// SHOW / HIDE PASSWORD
// ==========================================

if (togglePassword && passwordInput) {

    togglePassword.addEventListener("click", () => {

        if (passwordInput.type === "password") {

            passwordInput.type = "text";

            togglePassword.textContent = "Hide";

        } else {

            passwordInput.type = "password";

            togglePassword.textContent = "Show";

        }

    });

}


// ==========================================
// OPEN CREATE ACCOUNT
// ==========================================

if (showSignupButton) {

    showSignupButton.addEventListener("click", () => {

        if (loginView) {
            loginView.classList.add("hidden");
        }

        if (signupView) {
            signupView.classList.remove("hidden");
        }

        clearMessages();

    });

}


// ==========================================
// BACK TO SIGN IN
// ==========================================

if (showLoginButton) {

    showLoginButton.addEventListener("click", () => {

        if (signupView) {
            signupView.classList.add("hidden");
        }

        if (loginView) {
            loginView.classList.remove("hidden");
        }

        clearMessages();

    });

}


// ==========================================
// SIGN IN
// ==========================================

if (loginForm) {

    loginForm.addEventListener("submit", async (event) => {

        event.preventDefault();

        clearMessages();


        // Get login values
        const username = document
            .getElementById("username")
            .value
            .trim()
            .toLowerCase();

        const password = document
            .getElementById("password")
            .value
            .trim();

        const role = roleInput
            ? roleInput.value
            : "";


        // -------------------------------
        // VALIDATION
        // -------------------------------

        if (!role) {

            showMessage(
                loginMessage,
                "Please select your role.",
                "error"
            );

            return;

        }


        if (!username || !password) {

            showMessage(
                loginMessage,
                "Please enter your email and password.",
                "error"
            );

            return;

        }


        try {

            // -------------------------------
            // SEND LOGIN REQUEST
            // -------------------------------

            const response = await fetch(
                "/api/login",
                {

                    method: "POST",

                    headers: {
                        "Content-Type": "application/json"
                    },

                    body: JSON.stringify({

                        username: username,

                        password: password,

                        role: role

                    })

                }
            );


            const data = await response.json();


            // -------------------------------
            // LOGIN FAILED
            // -------------------------------

            if (!response.ok) {

                showMessage(
                    loginMessage,
                    data.message || "Invalid login details.",
                    "error"
                );

                return;

            }


            // -------------------------------
            // SAVE USER DETAILS
            // -------------------------------

            localStorage.setItem(
                "userName",
                data.user.name
            );

            localStorage.setItem(
                "userEmail",
                data.user.email
            );

            localStorage.setItem(
                "userRole",
                data.user.role
            );


            showMessage(
                loginMessage,
                "Login successful! Redirecting...",
                "success"
            );


            // -------------------------------
            // REDIRECT
            // -------------------------------

            setTimeout(() => {

                redirectToDashboard(
                    data.user.role
                );

            }, 700);


        } catch (error) {

            console.error(
                "Login Error:",
                error
            );

            showMessage(
                loginMessage,
                "Server connection failed. Please start Flask.",
                "error"
            );

        }

    });

}


// ==========================================
// CREATE ACCOUNT
// ==========================================

if (signupForm) {

    signupForm.addEventListener(
        "submit",
        async (event) => {

            event.preventDefault();

            clearMessages();


            // -------------------------------
            // GET VALUES
            // -------------------------------

            const fullName = document
                .getElementById("fullName")
                .value
                .trim();

            const email = document
                .getElementById("email")
                .value
                .trim()
                .toLowerCase();

            const role = document
                .getElementById("signupRole")
                .value;

            const password = document
                .getElementById("signupPassword")
                .value;

            const confirmPassword = document
                .getElementById("confirmPassword")
                .value;

            const terms = document
                .getElementById("terms")
                .checked;


            // -------------------------------
            // EMPTY FIELD CHECK
            // -------------------------------

            if (
                !fullName ||
                !email ||
                !role ||
                !password ||
                !confirmPassword
            ) {

                showMessage(
                    signupMessage,
                    "Please fill in all fields.",
                    "error"
                );

                return;

            }


            // -------------------------------
            // EMAIL VALIDATION
            // -------------------------------

            const emailPattern =
                /^[^\s@]+@[^\s@]+\.[^\s@]+$/;


            if (!emailPattern.test(email)) {

                showMessage(
                    signupMessage,
                    "Please enter a valid email address.",
                    "error"
                );

                return;

            }


            // -------------------------------
            // PASSWORD LENGTH
            // -------------------------------

            if (password.length < 6) {

                showMessage(
                    signupMessage,
                    "Password must contain at least 6 characters.",
                    "error"
                );

                return;

            }


            // -------------------------------
            // CONFIRM PASSWORD
            // -------------------------------

            if (password !== confirmPassword) {

                showMessage(
                    signupMessage,
                    "Passwords do not match.",
                    "error"
                );

                return;

            }


            // -------------------------------
            // TERMS CHECK
            // -------------------------------

            if (!terms) {

                showMessage(
                    signupMessage,
                    "Please accept the terms and privacy policy.",
                    "error"
                );

                return;

            }


            try {

                // ==========================================
                // SEND SIGNUP DATA TO FLASK
                // ==========================================

                const response = await fetch(
                    "/api/signup",
                    {

                        method: "POST",

                        headers: {
                            "Content-Type": "application/json"
                        },

                        body: JSON.stringify({

                            fullName: fullName,

                            email: email,

                            role: role,

                            password: password

                        })

                    }
                );


                const data = await response.json();


                // -------------------------------
                // SIGNUP FAILED
                // -------------------------------

                if (!response.ok) {

                    showMessage(
                        signupMessage,
                        data.message ||
                        "Account creation failed.",
                        "error"
                    );

                    return;

                }


                // -------------------------------
                // SAVE USER DETAILS
                // -------------------------------

                localStorage.setItem(
                    "userName",
                    data.user.name
                );

                localStorage.setItem(
                    "userEmail",
                    data.user.email
                );

                localStorage.setItem(
                    "userRole",
                    data.user.role
                );


                // -------------------------------
                // SUCCESS
                // -------------------------------

                showMessage(
                    signupMessage,
                    "Account created successfully! Redirecting...",
                    "success"
                );


                // -------------------------------
                // REDIRECT
                // -------------------------------

                setTimeout(() => {

                    redirectToDashboard(
                        data.user.role
                    );

                }, 700);


            } catch (error) {

                console.error(
                    "Signup Error:",
                    error
                );

                showMessage(
                    signupMessage,
                    "Server connection failed. Please start Flask.",
                    "error"
                );

            }

        }
    );

}


// ==========================================
// ROLE BASED DASHBOARD
// ==========================================

function redirectToDashboard(role) {

    if (role === "admin") {

        window.location.href =
            "admin_dashboard.html";

    }

    else if (role === "faculty") {

        window.location.href =
            "faculty_dashboard.html";

    }

    else if (role === "student") {

        window.location.href =
            "student_dashboard.html";

    }

    else {

        alert(
            "Invalid role selected."
        );

    }

}


// ==========================================
// FORGOT PASSWORD BUTTON
// ==========================================

const forgotPasswordButton =
    document.getElementById("forgotPassword");


if (forgotPasswordButton) {

    forgotPasswordButton.addEventListener(
        "click",
        (event) => {

            event.preventDefault();

            showForgotPassword();

        }
    );

}


// ==========================================
// FORGOT PASSWORD
// ==========================================

function showForgotPassword() {

    const email = prompt(
        "Enter your registered email address:"
    );


    if (!email) {
        return;
    }


    const cleanEmail =
        email.trim().toLowerCase();


    sendForgotPasswordOTP(
        cleanEmail
    );

}


// ==========================================
// SEND OTP
// ==========================================

async function sendForgotPasswordOTP(email) {

    try {

        const response = await fetch(
            "/api/forgot-password",
            {

                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({

                    email: email

                })

            }
        );


        const data = await response.json();


        if (!response.ok) {

            alert(
                data.message ||
                "Unable to send OTP."
            );

            return;

        }


        alert(
            "OTP sent successfully to your email."
        );


        // Go to OTP verification
        verifyOTP(email);


    } catch (error) {

        console.error(
            "Forgot Password Error:",
            error
        );

        alert(
            "Server connection failed. Please start Flask."
        );

    }

}


// ==========================================
// OTP VERIFICATION
// ==========================================

function verifyOTP(email) {

    const otp = prompt(
        "Enter the 6-digit OTP sent to your email:"
    );


    if (!otp) {
        return;
    }


    if (!/^\d{6}$/.test(otp)) {

        alert(
            "Please enter a valid 6-digit OTP."
        );

        return;

    }


    verifyOTPWithServer(
        email,
        otp
    );

}


// ==========================================
// VERIFY OTP WITH FLASK
// ==========================================

async function verifyOTPWithServer(
    email,
    otp
) {

    try {

        const response = await fetch(
            "/api/verify-otp",
            {

                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({

                    email: email,

                    otp: otp

                })

            }
        );


        const data = await response.json();


        if (!response.ok) {

            alert(
                data.message ||
                "Invalid OTP."
            );

            return;

        }


        alert(
            "OTP verified successfully!"
        );


        // Go to password reset
        resetPassword(email);


    } catch (error) {

        console.error(
            "OTP Verification Error:",
            error
        );

        alert(
            "Server connection failed. Please start Flask."
        );

    }

}


// ==========================================
// RESET PASSWORD
// ==========================================

function resetPassword(email) {

    const newPassword = prompt(
        "Enter your new password:"
    );


    if (!newPassword) {
        return;
    }


    const confirmPassword = prompt(
        "Confirm your new password:"
    );


    if (!confirmPassword) {
        return;
    }


    // -------------------------------
    // PASSWORD MATCH
    // -------------------------------

    if (newPassword !== confirmPassword) {

        alert(
            "Passwords do not match."
        );

        return;

    }


    // -------------------------------
    // PASSWORD LENGTH
    // -------------------------------

    if (newPassword.length < 6) {

        alert(
            "Password must contain at least 6 characters."
        );

        return;

    }


    resetPasswordWithServer(
        email,
        newPassword
    );

}


// ==========================================
// RESET PASSWORD WITH FLASK
// ==========================================

async function resetPasswordWithServer(
    email,
    newPassword
) {

    try {

        const response = await fetch(
            "/api/reset-password",
            {

                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({

                    email: email,

                    newPassword: newPassword

                })

            }
        );


        const data = await response.json();


        if (!response.ok) {

            alert(
                data.message ||
                "Password reset failed."
            );

            return;

        }


        alert(
            "Password reset successfully! Please sign in with your new password."
        );


        // -------------------------------
        // RETURN TO LOGIN
        // -------------------------------

        if (signupView) {

            signupView.classList.add(
                "hidden"
            );

        }

        if (loginView) {

            loginView.classList.remove(
                "hidden"
            );

        }


    } catch (error) {

        console.error(
            "Reset Password Error:",
            error
        );

        alert(
            "Server connection failed. Please start Flask."
        );

    }

}


// ==========================================
// SHOW MESSAGE
// ==========================================

function showMessage(
    element,
    text,
    type
) {

    if (!element) {
        return;
    }


    element.textContent = text;

    element.className = type;

}


// ==========================================
// CLEAR MESSAGES
// ==========================================

function clearMessages() {

    if (loginMessage) {

        loginMessage.textContent = "";

        loginMessage.className = "";

    }


    if (signupMessage) {

        signupMessage.textContent = "";

        signupMessage.className = "";

    }

}