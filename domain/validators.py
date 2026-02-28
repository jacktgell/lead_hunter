# domain/validators.py
import requests
from core.logger import get_logger

logger = get_logger(__name__)


class ApiEmailValidator:
    # Using QuickEmailVerification as an example (100 free/day)
    API_URL = "https://api.quickemailverification.com/v1/verify"

    @classmethod
    def is_deliverable(cls, email: str, api_key: str) -> bool:
        if not email or "@" not in email:
            return False

        if not api_key:
            logger.warning("No Verification API Key found. Skipping validation (Fail-Open).")
            return True

        try:
            params = {
                "email": email,
                "apikey": api_key
            }
            # Timeout is critical so the API doesn't hang your pipeline
            response = requests.get(cls.API_URL, params=params, timeout=5)

            if response.status_code == 200:
                data = response.json()
                # 'result' can be 'valid', 'invalid', or 'unknown'
                result = data.get("result", "unknown")

                if result == "invalid":
                    logger.info(f"API Rejected Email: {email} (Reason: {data.get('reason')})")
                    return False

                return True
            else:
                logger.error(f"Email API returned status {response.status_code}. Allowing email through.")
                return True  # Fail-open if the API goes down or you hit rate limits

        except requests.exceptions.RequestException as e:
            logger.error(f"Email Verification API connection failed: {e}")
            return True  # Fail-open so pipeline doesn't crash