"""Compatibility entry: the exploration panel now lives in ClawInstitute."""
import json
from scripts.cloud.runtime import RECORD

def main():
    record = json.loads(RECORD.read_text())
    if not record.get("frontend_enabled"):
        raise SystemExit("Restart the owned service with EXPLORE_FRONTEND=1; no separate workbench server is started.")
    print(f"ClawInstitute ExploreOS: http://127.0.0.1:{record['frontend_port']}/api/v1/exploreos/ui")

if __name__ == "__main__":
    main()
