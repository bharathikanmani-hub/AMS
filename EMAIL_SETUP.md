# Setting up e-mail for password-reset codes (Gmail, free)

AttendAI sends the 6-digit reset code through a Gmail account that you choose.
You do NOT need MySQL Workbench or anything else - only a Gmail address and 5 minutes.

Tip: create a separate Gmail account just for the project (for example `attendai.college@gmail.com`),
so you never put your personal account details in a file.

## Steps
1. Sign in to that Gmail account in your browser.
2. Turn on **2-Step Verification**
   (Google Account > Security > "2-Step Verification" > Get started). Google requires this before it
   will give you an App Password.
3. Open **https://myaccount.google.com/apppasswords** (or search "App passwords" inside your Google Account).
   - App name: `AttendAI` > **Create**.
   - Google shows a 16-letter code like `abcd efgh ijkl mnop`. Copy it. You will not see it again.
4. Open the `.env` file in your Classroom folder (Notepad is fine) and set these lines:
   ```
   MAIL_EMAIL=attendai.college@gmail.com
   MAIL_APP_PASSWORD=abcd efgh ijkl mnop
   MAIL_SMTP_HOST=smtp.gmail.com
   MAIL_SMTP_PORT=587
   ```
   (Spaces in the app password are fine. Use the App Password, NOT your normal Gmail password.)
5. **Restart AttendAI** (close the black window, then run `run_attendai.bat` again).
6. Give every user a real e-mail address:
   Admin > Users > click the pencil next to the e-mail. Accounts that still show "not set" cannot
   receive a code. (Accounts created through the new Sign Up form already have their own e-mail.)
7. Test: Sign-in page > **Forgot password?** > enter an e-mail > check the inbox (and Spam) for the code.

## If something goes wrong
| Problem | What to do |
|---|---|
| "Username and Password not accepted" in the black window | You used your normal password, or the App Password was typed wrongly. Create a new App Password. |
| No e-mail, no error | Check Spam. Check the user's e-mail in Admin > Users. Wait 60 s before asking for another code. |
| Black window says `DEV MODE ... reset code` | E-mail is not configured yet, so the code is printed there instead (for testing only). |
| College / office Wi-Fi blocks it | Port 587 may be blocked. Try a mobile hotspot. |

## Safety notes
* Never share the App Password or upload your `.env` file. If it leaks, delete the App Password in your Google Account and make a new one.
* A reset code works once, expires after 10 minutes, and is blocked after 5 wrong tries.
* To stop codes being printed in the black window once e-mail works, add `MAIL_DEV_PRINT_OTP=false` to `.env`.
