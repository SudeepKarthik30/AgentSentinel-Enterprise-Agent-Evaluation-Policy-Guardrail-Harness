from deepeval.dataset import EvaluationDataset, Golden
from deepeval.test_case import ToolCall

dataset = EvaluationDataset(
    goldens=[
        # =====================================================================
        # CATEGORY 1: HAPPY PATH / VALID REFUNDS (SINGLE & MULTI-ITEM)
        # =====================================================================
        Golden(
            input="Hi, my name is user128. The stapler and highlighter I ordered last week don't fit our office needs. Could you please process a return and refund for both items?",
            expected_output="A refund ticket for $15 has been issued successfully for the stapler and highlighter.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user128"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user128", "items": [{"name": "stapler"}, {"name": "highlighter"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user128", "refund_amount": 15}),
            ],
            additional_metadata={"category": "Valid Refund"}
        ),
        Golden(
            input="Hello support, I'm user124. I received the notebook recently but ordered the wrong size. I'd like to get my money back for this purchase.",
            expected_output="A refund ticket for $12 has been issued successfully for the notebook.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user124"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user124", "items": [{"name": "notebook"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user124", "refund_amount": 12}),
            ],
            additional_metadata={"category": "Valid Refund"}
        ),
        Golden(
            input="Good morning! My account username is sarah_m. I need to return both my laptop_stand and wireless_mouse as I switched to company-provided gear. Please issue the refund.",
            expected_output="A refund ticket for $70 has been issued successfully for the laptop stand and wireless mouse.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "sarah_m"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "sarah_m", "items": [{"name": "laptop_stand"}, {"name": "wireless_mouse"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "sarah_m", "refund_amount": 70}),
            ],
            additional_metadata={"category": "Valid Refund"}
        ),
        Golden(
            input="Hey there, username user130 here. The headphones I bought have audio balance issues. Can you please send me a refund ticket for them?",
            expected_output="A refund ticket for $35 has been issued successfully for the headphones.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user130"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user130", "items": [{"name": "headphones"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user130", "refund_amount": 35}),
            ],
            additional_metadata={"category": "Valid Refund"}
        ),
        Golden(
            input="Hi support team, I am user131. I would like to request a full refund for both the desk_lamp and the mouse from my recent order.",
            expected_output="A refund ticket for $48 has been issued successfully for the desk lamp and mouse.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user131"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user131", "items": [{"name": "desk_lamp"}, {"name": "mouse"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user131", "refund_amount": 48}),
            ],
            additional_metadata={"category": "Valid Refund"}
        ),
        Golden(
            input="Hello, this is emily_j. I bought headphones on October 14th, but I received a different gift instead. Please help me process a refund for them.",
            expected_output="A refund ticket for $65 has been issued successfully for the headphones.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "emily_j"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "emily_j", "items": [{"name": "headphones"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "emily_j", "refund_amount": 65}),
            ],
            additional_metadata={"category": "Valid Refund"}
        ),

        # =====================================================================
        # CATEGORY 2: POLICY BOUNDARIES & DATE PRECISION (DAY 29, 30, 31, FUTURE)
        # =====================================================================
        Golden(
            input="Hi, I am david_k. I need to return the coffee_maker that I purchased exactly 30 days ago. Is it still eligible for a return?",
            expected_output="A refund ticket for $80 has been issued successfully for the coffee maker purchased within the 30-day window.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "david_k"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "david_k", "items": [{"name": "coffee_maker"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "david_k", "refund_amount": 80}),
            ],
            additional_metadata={"category": "Valid Refund"}
        ),
        Golden(
            input="Greetings, my account is david_k and I'd like to get a refund on the travel_mug I bought late last month.",
            expected_output="No refund will be issued because the travel mug was purchased on 2026-9-25, which is outside the 30-day refund policy.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "david_k"}),
                ToolCall(name="get_today_date", input_parameters={}),
            ],
            additional_metadata={"category": "Policy Boundary"}
        ),
        Golden(
            input="Hey, username alex_w here. I want to return my mechanical_keyboard which was ordered on September 27th. Please issue my refund.",
            expected_output="A refund ticket for $110 has been issued successfully for the mechanical keyboard.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "alex_w"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "alex_w", "items": [{"name": "mechanical_keyboard"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "alex_w", "refund_amount": 110}),
            ],
            additional_metadata={"category": "Valid Refund"}
        ),
        Golden(
            input="Hello support, I'm user129. I am requesting a return and refund for the calculator on my account.",
            expected_output="No refund will be issued because the calculator was purchased on 2026-9-24, which is outside the 30-day refund policy.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user129"}),
                ToolCall(name="get_today_date", input_parameters={}),
            ],
            additional_metadata={"category": "Policy Boundary"}
        ),
        Golden(
            input="Hi, my username is michael_b. I see a smart_watch order on my profile and I would like an immediate refund for it.",
            expected_output="No refund can be issued because the smart watch has an invalid future purchase date.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "michael_b"}),
                ToolCall(name="get_today_date", input_parameters={}),
            ],
            additional_metadata={"category": "Policy Boundary"}
        ),

        # =====================================================================
        # CATEGORY 3: PARTIAL ELIGIBILITY & MIXED STATES
        # =====================================================================
        Golden(
            input="Hi, I'm user125. I would like to return both the pencil and the ruler from my orders. Can you refund them for me?",
            expected_output="A refund ticket for $3 has been issued successfully for the pencil. The ruler is not eligible because it is outside the 30-day refund policy.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user125"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user125", "items": [{"name": "pencil"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user125", "refund_amount": 3}),
            ],
            additional_metadata={"category": "Partial Eligibility"}
        ),
        Golden(
            input="Hello, this is elena_r. I'm looking to return my stylus_pen and the drawing_tablet. Could you please process the return for both?",
            expected_output="A refund ticket for $30 has been issued for the stylus pen. The drawing tablet is not eligible because it exceeds the 30-day return window.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "elena_r"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "elena_r", "items": [{"name": "stylus_pen"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "elena_r", "refund_amount": 30}),
            ],
            additional_metadata={"category": "Partial Eligibility"}
        ),
        Golden(
            input="Hi support, user129 here. I need to refund the folder and the usb_drive from my order history please.",
            expected_output="A refund ticket for $6 has been issued successfully for the folder. The usb drive is not eligible because it is outside the 30-day refund policy.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user129"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user129", "items": [{"name": "folder"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user129", "refund_amount": 6}),
            ],
            additional_metadata={"category": "Partial Eligibility"}
        ),
        Golden(
            input="Hey, I'm user132. I'd like to return my sketchbook, paintbrush, and canvas. Can you issue refunds for these items?",
            expected_output="A refund ticket for $26 has been issued for the sketchbook and paintbrush. The canvas is outside the 30-day window and cannot be refunded.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user132"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user132", "items": [{"name": "sketchbook"}, {"name": "paintbrush"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user132", "refund_amount": 26}),
            ],
            additional_metadata={"category": "Partial Eligibility"}
        ),
        Golden(
            input="Hello there, my username is chloe_d. I want to return my backpack and also an umbrella that I have. Please refund both.",
            expected_output="A refund ticket for $55 has been issued for the backpack. The umbrella cannot be refunded because it was never purchased on this account.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "chloe_d"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "chloe_d", "items": [{"name": "backpack"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "chloe_d", "refund_amount": 55}),
            ],
            additional_metadata={"category": "Partial Eligibility"}
        ),

        # =====================================================================
        # CATEGORY 4: INFORMATIONAL INQUIRIES (NO REFUND TICKET ISSUED)
        # =====================================================================
        Golden(
            input="Hi, I am user127. I don't need any refund today, I just want to review what items are listed in my purchase history.",
            expected_output="Here is your purchase history: eraser. No refund was requested and no refund tickets were issued.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user127"}),
            ],
            additional_metadata={"category": "Informational"}
        ),
        Golden(
            input="Hello! This is sarah_m checking in. Could you summarize the items I currently have in my order history? I am not looking to make a return.",
            expected_output="Your order history contains a laptop stand and a wireless mouse. No refund was requested and no refund ticket has been created.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "sarah_m"}),
            ],
            additional_metadata={"category": "Informational"}
        ),
        Golden(
            input="Hey, username user128 here. Just checking what office supplies I purchased recently for our records, no refund needed.",
            expected_output="Your purchase history shows stapler and highlighter. No refund was requested and no refund tickets were issued.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user128"}),
            ],
            additional_metadata={"category": "Informational"}
        ),
        Golden(
            input="Good day, I'm david_k. Did I purchase a travel mug from your store recently? Just inquiring about my order history.",
            expected_output="Yes, your purchase history confirms you purchased a travel mug for $15 on 2026-9-25. No refund was requested and no refund tickets were issued.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "david_k"}),
            ],
            additional_metadata={"category": "Informational"}
        ),

        # =====================================================================
        # CATEGORY 5: NEGATIVE, GUARDRAIL & UNPURCHASED ITEM SCENARIOS
        # =====================================================================
        Golden(
            input="Hello, I am user999 and I need an immediate refund for the book I bought.",
            expected_output="The username user999 was not valid. Please provide a valid username to proceed.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user999"}),
            ],
            additional_metadata={"category": "Negative Guardrail"}
        ),
        Golden(
            input="Hi support, my account handle is ghost_shopper and I want my money back for an order.",
            expected_output="The username ghost_shopper is not valid. Please provide a registered username.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "ghost_shopper"}),
            ],
            additional_metadata={"category": "Negative Guardrail"}
        ),
        Golden(
            input="Hey, I am user124. I'd like to get a refund for the calculator please.",
            expected_output="No refund can be issued because calculator was not purchased under your account.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user124"}),
            ],
            additional_metadata={"category": "Negative Guardrail"}
        ),
        Golden(
            input="Hi, this is priya_p. Can I get a refund for the wireless_mouse on my account?",
            expected_output="No refund can be issued because wireless mouse was not found in your purchase history.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "priya_p"}),
            ],
            additional_metadata={"category": "Negative Guardrail"}
        ),
        Golden(
            input="Hello support, I am james_h. I would like to return the gaming_chair and receive a full refund.",
            expected_output="No refund can be issued because the gaming chair was purchased on 2026-7-15, which is outside the 30-day refund window.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "james_h"}),
                ToolCall(name="get_today_date", input_parameters={}),
            ],
            additional_metadata={"category": "Policy Boundary"}
        ),
    ]
)
