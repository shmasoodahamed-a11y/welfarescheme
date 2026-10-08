import http.server
import json
import os
import re
import socketserver
import secrets

PORT = int(os.environ.get("PORT", 8000))
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "schemes.json")
STATIC_HTML = os.path.join(os.path.dirname(__file__), "static", "index.html")

# Updated Credentials Store with Mobile Numbers
OFFICIAL_CREDENTIALS = {
    "admin_manipur": {"password": "gov_sw_2026", "phone": "9366118850"},
    "officer_welfare": {"password": "sw_manipur_2026", "phone": "8257968322"}
}

ACTIVE_TOKENS = set()
OTP_STORE = {}  # Temporarily stores { "username": "1234" }

def load_schemes():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_schemes(schemes):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(schemes, f, indent=2, ensure_ascii=False)

def parse_natural_circumstance(query_text: str):
    text = query_text.lower()
    profile = {
        "age": 28, "category": "General", "occupation": "unemployed",
        "annual_income": 120000.0, "is_pwd": False, "is_bpl_or_aay": False
    }

    age_match = re.search(r'(\d{1,2})\s*(?:years|yr|yrs|age|old)', text)
    if age_match: profile["age"] = int(age_match.group(1))
    elif any(k in text for k in ["senior", "elderly", "old age", "ahall"]): profile["age"] = 65

    if any(k in text for k in ["disabled", "disability", "pwd", "handicap", "blind", "deaf", "shotharaba"]): profile["is_pwd"] = True
    if any(k in text for k in ["bpl", "aay", "poor", "ration card", "destitute", "widow", "low income"]): profile["is_bpl_or_aay"] = True
    
    if "st" in text or "tribe" in text: profile["category"] = "ST"
    elif "sc" in text or "caste" in text: profile["category"] = "SC"
    elif "obc" in text: profile["category"] = "OBC"

    if any(k in text for k in ["student", "study", "college", "school", "maheiroi"]): profile["occupation"] = "student"
    elif any(k in text for k in ["farmer", "agriculture", "cultivator", "kisan", "loumi"]): profile["occupation"] = "farmer"
    elif any(k in text for k in ["athlete", "sports", "player", "sportsperson", "football", "boxing"]): profile["occupation"] = "athlete"
    elif any(k in text for k in ["labor", "labour", "mason", "carpenter", "construction", "artisan", "daily wage"]): profile["occupation"] = "daily wage / artisan"

    return profile

def evaluate_scheme_eligibility(scheme: dict, profile: dict):
    crit = scheme.get("criteria", {})
    reasons = []

    if crit.get("is_pwd"):
        if not profile.get("is_pwd", False): return None
        reasons.append("Matches benchmark disability (PwD) requirement")

    if "min_age" in crit and profile.get("age", 0) < crit["min_age"]: return None
    if "max_age" in crit and profile.get("age", 0) > crit["max_age"]: return None
    if "min_age" in crit: reasons.append(f"Meets minimum age threshold of {crit['min_age']} years")

    if crit.get("bpl_or_aay"):
        if not (profile.get("is_bpl_or_aay", False) or profile.get("is_pwd", False)): return None
        reasons.append("Eligible under BPL/AAY socio-economic or PwD criterion")

    if "max_family_income" in crit:
        if profile.get("annual_income", 0) > crit["max_family_income"]: return None
        reasons.append(f"Annual income within ceiling limit of ₹{crit['max_family_income']:,}")

    if "category" in crit:
        allowed = [c.upper() for c in crit["category"]]
        user_cat = profile.get("category", "General").upper()
        if user_cat not in allowed: return None
        reasons.append(f"Belongs to eligible community category ({user_cat})")

    if "occupation" in crit:
        required_occ = crit["occupation"].lower()
        user_occ = profile.get("occupation", "").lower()
        if required_occ != user_occ: return None
        reasons.append(f"Eligible under occupation profile ({user_occ.title()})")

    if not reasons: reasons.append("Matches general citizen eligibility criteria")

    scheme_result = scheme.copy()
    scheme_result["match_reasons"] = reasons
    return scheme_result

class SchemeNavigatorHandler(http.server.SimpleHTTPRequestHandler):
    def send_json(self, status_code, payload):
        response_bytes = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

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
        content_length = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try: data = json.loads(post_body)
        except Exception: data = {}

        if self.path == "/api/match-schemes":
            query_str = data.get("natural_query", "").strip()
            if query_str: profile = parse_natural_circumstance(query_str)
            else:
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
                "extracted_profile": profile,
                "total_matched": len(matched),
                "statutory_disclaimer": "Advisory Notice: Guidance provided by this navigator is for informational purposes only. Final eligibility determination and sanction rest solely with the respective government department.",
                "results": matched
            })

        elif self.path == "/api/admin/login":
            u = data.get("username", "").strip()
            p = data.get("password", "").strip()
            # Updated login to check nested dictionary
            if u in OFFICIAL_CREDENTIALS and OFFICIAL_CREDENTIALS[u]["password"] == p:
                token = secrets.token_hex(16)
                ACTIVE_TOKENS.add(token)
                self.send_json(200, {"status": "authenticated", "token": token, "officer": u})
            else:
                self.send_json(401, {"error": "Invalid official credentials."})

        # --- NEW: Request OTP Endpoint ---
        elif self.path == "/api/admin/request-otp":
            u = data.get("username", "").strip()
            phone = data.get("phone", "").strip()
            
            if u in OFFICIAL_CREDENTIALS and OFFICIAL_CREDENTIALS[u]["phone"] == phone:
                otp = str(secrets.randbelow(9000) + 1000) # Generates a 4-digit OTP
                OTP_STORE[u] = otp
                # Print to backend terminal to simulate SMS
                print(f"\n[{u}] SIMULATED SMS to +91-{phone}: Your Manipur Portal Reset OTP is {otp}\n")
                self.send_json(200, {"status": "success", "demo_otp": otp})
            else:
                self.send_json(400, {"error": "User ID and Mobile Number do not match our records."})

        # --- NEW: Reset Password Endpoint ---
        elif self.path == "/api/admin/reset-password":
            u = data.get("username", "").strip()
            otp = data.get("otp", "").strip()
            new_pass = data.get("new_password", "").strip()

            if u in OTP_STORE and OTP_STORE[u] == otp:
                OFFICIAL_CREDENTIALS[u]["password"] = new_pass
                del OTP_STORE[u] # Invalidate OTP
                self.send_json(200, {"status": "success", "message": "Password updated securely."})
            else:
                self.send_json(400, {"error": "Invalid or expired OTP."})

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
                    if updated_desc: s["description"]["en"] = updated_desc
                    if max_income is not None and "criteria" in s: s["criteria"]["max_family_income"] = float(max_income)
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