"""
Morphy Web Studio
Zero-dependency local web dashboard for creating Morphe patches visually in your browser.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import webbrowser
import logging
from pathlib import Path
from morphy_creator.core.agent import AutonomousPatchAgent
from morphy_creator.presets.catalog import RecipeManager

logger = logging.getLogger("morphy.web_studio")

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Morphy Patches Creator - Web Studio</title>
  <style>
    :root {
      --bg: #0A0314;
      --card: #140924;
      --accent: #FF71CE;
      --cyan: #00FFAA;
      --purple: #9333EA;
      --text: #F3E8FF;
    }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      margin: 0;
      padding: 30px;
      display: flex;
      flex-direction: column;
      align-items: center;
    }
    .header {
      text-align: center;
      margin-bottom: 25px;
    }
    h1 {
      font-size: 2.2rem;
      background: linear-gradient(135deg, var(--cyan), var(--accent));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin: 0 0 8px 0;
    }
    .card {
      background: var(--card);
      border: 1px solid #2B154A;
      border-radius: 16px;
      padding: 24px;
      width: 100%;
      max-width: 650px;
      box-shadow: 0 8px 30px rgba(0,0,0,0.5);
      margin-bottom: 20px;
    }
    label {
      font-weight: bold;
      display: block;
      margin-top: 14px;
      margin-bottom: 6px;
      color: var(--cyan);
    }
    input[type="text"] {
      width: 100%;
      padding: 12px;
      background: #0E051C;
      border: 1px solid #3B1C66;
      border-radius: 8px;
      color: #FFF;
      box-sizing: border-box;
      font-size: 1rem;
    }
    .presets {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 10px;
    }
    .preset-btn {
      background: #1C0D33;
      border: 1px solid #4B2482;
      color: #DDD;
      padding: 10px;
      border-radius: 8px;
      cursor: pointer;
      text-align: left;
      font-size: 0.9rem;
      transition: all 0.2s;
    }
    .preset-btn:hover {
      border-color: var(--accent);
      color: #FFF;
      background: #251244;
    }
    .btn-create {
      background: linear-gradient(135deg, var(--purple), var(--accent));
      color: #FFF;
      border: none;
      padding: 14px 28px;
      font-size: 1.1rem;
      font-weight: bold;
      border-radius: 10px;
      cursor: pointer;
      width: 100%;
      margin-top: 24px;
      transition: opacity 0.2s;
    }
    .btn-create:hover {
      opacity: 0.9;
    }
    #status {
      margin-top: 16px;
      padding: 12px;
      border-radius: 8px;
      display: none;
      font-weight: bold;
    }
    .success { background: #0A3322; border: 1px solid #00FFAA; color: #00FFAA; }
    .error { background: #3B0D18; border: 1px solid #FF3366; color: #FF3366; }
  </style>
</head>
<body>
  <div class="header">
    <h1>Morphy Patches Creator</h1>
    <p style="color:#A78BFA;margin:0;">Visual Web Studio - Zero Coding Patch Engineering</p>
  </div>

  <div class="card">
    <label>1. Target APK Path</label>
    <input type="text" id="apk_path" placeholder="e.g. C:\\path\\to\\app.apk or /home/user/app.apk">

    <label>2. Quick Preset Recipes</label>
    <div class="presets">
      <div class="preset-btn" onclick="setPreset('Remove all ads and promotional banners')">🚫 Ad Removal</div>
      <div class="preset-btn" onclick="setPreset('Force pure AMOLED black dark theme')">🌙 AMOLED Theme</div>
      <div class="preset-btn" onclick="setPreset('Allow screenshots in protected screens')">📸 Allow Screenshots</div>
      <div class="preset-btn" onclick="setPreset('Bypass root detection checks')">🛡️ Bypass Root Check</div>
    </div>

    <label>3. Or Describe in Plain Words</label>
    <input type="text" id="prompt" placeholder="e.g. Unlock full pro features and remove watermarks">

    <button class="btn-create" onclick="createPatch()">✨ Generate Morphe Patch (.mpp)</button>
    <div id="status"></div>
  </div>

  <script>
    function setPreset(val) {
      document.getElementById('prompt').value = val;
    }

    async function createPatch() {
      const apk = document.getElementById('apk_path').value.trim();
      const prompt = document.getElementById('prompt').value.trim();
      const status = document.getElementById('status');

      if (!apk || !prompt) {
        status.className = 'error';
        status.innerText = 'Please specify both an APK path and a patch goal.';
        status.style.display = 'block';
        return;
      }

      status.className = '';
      status.style.display = 'block';
      status.style.background = '#2B154A';
      status.style.color = '#FFF';
      status.innerText = '🤖 Morphy AI is analyzing APK and synthesizing patch...';

      try {
        const resp = await fetch('/api/create', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({apk, prompt})
        });
        const res = await resp.json();
        if (res.status === 'success') {
          status.className = 'success';
          status.innerText = '✔ Patch synthesized successfully! Bundle saved at: ' + res.bundle_file;
        } else {
          status.className = 'error';
          status.innerText = 'Error: ' + (res.error || 'Patch generation failed.');
        }
      } catch (err) {
        status.className = 'error';
        status.innerText = 'Server error: ' + err.message;
      }
    }
  </script>
</body>
</html>
"""

class StudioHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_DASHBOARD.encode("utf-8"))
        elif self.path == "/api/recipes":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            recipes = RecipeManager.list_recipes()
            self.wfile.write(json.dumps(recipes).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/create":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode("utf-8"))
                apk = Path(data.get("apk", ""))
                prompt = data.get("prompt", "")
                agent = AutonomousPatchAgent()
                out_dir = Path("./web_studio_patches")
                res = agent.auto_create_patch(apk, prompt, out_dir)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "error": str(e)}).encode("utf-8"))

def start_web_studio(port: int = 8765, open_browser: bool = True):
    server = HTTPServer(("127.0.0.1", port), StudioHandler)
    url = f"http://localhost:{port}"
    logger.info(f"Morphy Web Studio running at {url}")
    print(f"\n[OK] Morphy Web Studio live at: {url}")
    print("[INFO] Press Ctrl+C to stop the local studio.\n")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping Web Studio.")
        server.server_close()
