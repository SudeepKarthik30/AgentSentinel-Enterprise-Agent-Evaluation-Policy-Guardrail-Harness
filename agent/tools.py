from datetime import date, timedelta
import logging
from dotenv import load_dotenv
from langchain.tools import tool
from data import users_data
from objects import PurchaseItem

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s "
)

@tool
def get_user_purchase_history(user: str) -> dict:
    """This tool takes the username and returns a dict of the user's purchase
    history if the user exists."""
    logging.info(f"using get_user_purchase_history tool on user: {user}")
    
    if users_data.get(user):
        return users_data[user]

    return {"Status": "There was no username found"}


@tool
def calculate_right_refund(user: str, items: list[PurchaseItem]) -> str:
    """This tool takes a list of the eligible items to be returned and 
    the username and returns how much the refund is worth."""
    logging.info(f"using calculate_right_refund tool to get user's: {user} refund")

    if users_data.get(user):
        total_refund = 0
        for item in items:
            if users_data[user].get(item.name):
                total_refund += users_data[user][item.name]["price"]
        return f"The value of the refund is: {total_refund}"
    
    return {"Status": "There was no username found"}


@tool
def issue_refund_ticket(user: str, refund_amount: int) -> str:
    """This tool sends a ticket to the refund processing team to 
    issue the refund to the user."""
    logging.info(f"using issue_refund_ticket tool to get user's: {user}")

    return f"A refund ticket has been issued successfully with the amount of {refund_amount}"


@tool
def get_today_date() -> str:
    """This tool returns today's current date and the 30-day refund eligibility cutoff date."""
    logging.info("using the get_today_date tool")
    today = date.today()
    cutoff = today - timedelta(days=30)
    return (
        f"Today's date is {today.isoformat()} ({today.strftime('%B %d, %Y')}). "
        f"The 30-day refund cutoff date is {cutoff.isoformat()} ({cutoff.strftime('%B %d, %Y')}). "
        f"Purchases made on or after {cutoff.isoformat()} and on or before {today.isoformat()} are within the 30-day window and ELIGIBLE for refund. "
        f"Purchases dated before {cutoff.isoformat()} or with future dates after {today.isoformat()} are INELIGIBLE."
    )
