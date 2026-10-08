import http.server
import json
import os
import socketserver
import secrets

PORT = int(os.environ.get("PORT", 8000))
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "schemes.json")
STATIC_HTML = os.path.join(os.path.dirname(__file__), "static", "index.html")

OFFICIAL_CREDENTIALS = {
    "admin_manipur": "gov_sw_2026",
    "officer_welfare": "sw_manipur_2026"
}
ACTIVE_TOKENS = set()

def load_schemes():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_schemes(schemes):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(schemes, f, indent=2, ensure_ascii=False)

def evaluate_scheme_eligibility(scheme: dict, profile: dict):
    crit = scheme.get("criteria", {})
    reasons = []

    if crit.get("is_pwd"):
        if not profile.get("is_pwd", False):
            return None
        reasons.append("Matches benchmark disability (PwD) requirement")

    if "min_age" in crit and profile.get("age", 0) < crit["min_age"]:
        return None
    if "max_age" in crit and profile.get("age", 0) > crit["max_age"]:
        return None
    if "min_age" in crit:
        reasons.append(f"Meets minimum age threshold of {crit['min_age']} years")

    if crit.get("bpl_or_aay"):
        if not (profile.get("is_bpl_or_aay", False) or profile.get("is_pwd", False)):
            return None
        reasons.append("Eligible under BPL/AAY socio-economic or PwD criterion")

    if "max_family_income" in crit:
        if profile.get("annual_income", 0) > crit["max_family_income"]:
            return None
        reasons.append(f"Annual income within ceiling limit of ₹{crit['max_family_income']:,}")

    if "category" in crit:
        allowed = [c.upper() for c in crit["category"]]
        user_cat = profile.get("category", "General").upper()
        if user_cat not in allowed:
            return None
        reasons.append(f"Belongs to eligible community category ({user_cat})")

    if "occupation" in crit:
        if crit["occupation"].lower() != profile.get("occupation", "").lower():
            return None
        reasons.append(f"Eligible under occupation profile ({profile.get('occupation', '').title()})")

    if not reasons:
        reasons.append("Matches general citizen eligibility criteria")

    res = scheme.copy()
    res["match_reasons"] = reasons
    return res

class SchemeNavigatorHandler(http.server.SimpleHTTPRequestHandler):
    def send_json(self, status_code, payload):
        res = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(res)))
        self.end_headers()
        self.wfile.write(res)

    def do_GET(self):
        if self.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(STATIC_HTML, "rb") as f:
                self.wfile.write(f.read())
        elif self.path == "/api/admin/schemes":
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            if token not in ACTIVE_TOKENS:
                self.send_json(401, {"error": "Unauthorized session."})
                return
            self.send_json(200, {"schemes": load_schemes()})
        else:
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if self.path == "/api/match-schemes":
            profile = {
                "age": int(data.get("age", 28)),
                "category": data.get("category", "General"),
                "occupation": data.get("occupation", "unemployed").lower(),
                "annual_income": float(data.get("annual_income", 120000)),
                "is_pwd": bool(data.get("is_pwd", False)),
                "is_bpl_or_aay": bool(data.get("is_bpl_or_aay", False))
            }

            all_schemes = load_schemes()
            matched = [res for s in all_schemes if (res := evaluate_scheme_eligibility(s, profile))]

            self.send_json(200, {
                "status": "success",
                "total_matched": len(matched),
                "statutory_disclaimer": "Advisory Notice: Guidance provided by this navigator is for informational purposes only. Final eligibility determination and sanction rest solely with the respective government department.",
                "results": matched
            })

        elif self.path == "/api/admin/login":
            u = data.get("username", "").strip()
            p = data.get("password", "").strip()
            if OFFICIAL_CREDENTIALS.get(u) == p:
                token = secrets.token_hex(16)
                ACTIVE_TOKENS.add(token)
                self.send_json(200, {"status": "authenticated", "token": token, "officer": u})
            else:
                self.send_json(401, {"error": "Invalid official credentials."})

        elif self.path == "/api/admin/update-scheme":
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
            if token not in ACTIVE_TOKENS:
                self.send_json(401, {"error": "Unauthorized session."})
                return

            scheme_id = data.get("id")
            updated_desc = data.get("description_en")
            max_income = data.get("max_family_income")

            schemes = load_schemes()
            found = False
            for s in schemes:
                if s["id"] == scheme_id:
                    found = True
                    if updated_desc:
                        s["description"]["en"] = updated_desc
                    if max_income is not None and "criteria" in s:
                        s["criteria"]["max_family_income"] = float(max_income)
                    break

            if found:
                save_schemes(schemes)
                self.send_json(200, {"status": "success", "message": f"Scheme {scheme_id} updated."})
            else:
                self.send_json(404, {"error": "Scheme not found."})
        else:
            self.send_json(404, {"error": "Endpoint not found"})

class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    with ReusableTCPServer(("", PORT), SchemeNavigatorHandler) as httpd:
        print(f"Server live at http://127.0.0.1:{PORT}")
        httpd.serve_forever()