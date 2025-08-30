# Notes & tips

## How to create a session file
In the code, you will find this line - `insta.load_session_from_file('USERNAME')`. For it to work properly, you have to create a session file first, ahead of starting the script. 
How to do that:

- SSH into cuteframe
- Disable write protection
- Load up the venv `source venv/bin/activate`
- In the venv, start an interactive python session `python`
- Enter `import instaloader`, then `interactive_login('USERNAME')` (replace USERNAME with your username)
- Once successfully logged in, call `save_session_to_file()` to save the session locally
- Re-enable write protection
