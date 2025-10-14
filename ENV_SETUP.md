Local .env setup

1) Copy the template to a working .env in the project root (do NOT commit):

   Copy-Item .env.template .env

2) Edit the `.env` to add your secrets (PowerShell example):

   (Get-Content .env) -replace 'OPENAI_API_KEY=sk-.*', 'OPENAI_API_KEY=sk-REPLACE_ME' | Set-Content .env

   # or just open in an editor and paste your key

3) Load the .env into your PowerShell session (temporary):

   Get-Content .env | ForEach-Object {
     if ($_ -match "^\s*([^#=]+)=\s*(.*)\s*$") {
       $name = $matches[1].Trim(); $value = $matches[2].Trim(); Set-Item -Path Env:$name -Value $value
     }
   }

   # Confirm:
   echo $env:OPENAI_API_KEY

4) To persist for your user (Windows), use setx (will take effect in new shells):

   setx OPENAI_API_KEY "sk-REPLACE_ME"
   setx OPENAI_ENABLED "true"
   setx OPENAI_MAX_PER_MINUTE "10"

Security notes:
- Never commit `.env` to git. Keep it in your local machine only.
- If you accidentally exposed a key (e.g. pasted in chat), rotate it immediately in the provider dashboard.

If you'd like I can also add code to automatically load `.env` at app startup using python-dotenv; let me know if you want that.

To enable automatic loading during app startup, install python-dotenv in your environment:

```powershell
pip install python-dotenv
```

The app will attempt to import and load `.env` on startup; if python-dotenv is not installed the app will continue and print a short message telling you how to enable it.