from deepeval.dataset import EvaluationDataset, Golden
from deepeval.test_case import ToolCall

dataset = EvaluationDataset(
    goldens=[
        # CATEGORY 1: HAPPY PATH / VALID REFUNDS (SINGLE & MULTI-IT
        Golden(
            input="I am user123, I would like a refund for the book and the pen",
            expected_output="A refund ticket for $30 has been issued successfully for the book and pen.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user123"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user123", "items": [{"name": "book"}, {"name": "pen"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user123", "refund_amount": 30}),
            ]
        ),
        Golden(
            input="I am user123, I would like a refund for the book",
            expected_output="A refund ticket for $23 has been issued successfully for the book.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user123"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user123", "items": [{"name": "book"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user123", "refund_amount": 23}),
            ]
        ),
        Golden(
            input="Hi, I'm sarah_m. I'd like to return my laptop_stand please.",
            expected_output="A refund ticket with the amount of $45 was issued and should be arriving soon to your bank account.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "sarah_m"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "sarah_m", "items": [{"name": "laptop_stand"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "sarah_m", "refund_amount": 45}),
            ]
        ),
        Golden(
            input="Hello, my username is sarah_m and I want to return both the laptop_stand and the wireless_mouse.",
            expected_output="A refund ticket for $70 was issued successfully for the laptop stand and wireless mouse.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "sarah_m"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "sarah_m", "items": [{"name": "laptop_stand"}, {"name": "wireless_mouse"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "sarah_m", "refund_amount": 70}),
            ]
        ),
        Golden(
            input="Hi there, username chloe_d here. Could I get a refund for the backpack?",
            expected_output="A refund ticket for $55 was issued successfully for the backpack.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "chloe_d"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "chloe_d", "items": [{"name": "backpack"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "chloe_d", "refund_amount": 55}),
            ]
        ),
        Golden(
            input="I'm priya_p and I'd like to return the desk_mat I ordered recently.",
            expected_output="A refund ticket with the amount of $22 was issued successfully for the desk mat.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "priya_p"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "priya_p", "items": [{"name": "desk_mat"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "priya_p", "refund_amount": 22}),
            ]
        ),

        
        # CATEGORY 2: POLICY BOUNDARIES & DATE PRECISION (DAY 29, 30, 31, FUTURE)
        
        Golden(
            input="Hi, I am david_k. I need to return the coffee_maker.",
            expected_output="A refund ticket for $80 was issued successfully for the coffee maker purchased exactly on the 30-day boundary.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "david_k"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "david_k", "items": [{"name": "coffee_maker"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "david_k", "refund_amount": 80}),
            ]
        ),
        Golden(
            input="Hello, I am david_k, requesting a refund for the travel_mug.",
            expected_output="No refund will be issued because the travel mug was purchased on 2026-9-25, which is 31 days ago and exceeds the 30-day refund policy.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "david_k"}),
                ToolCall(name="get_today_date", input_parameters={}),
            ]
        ),
        Golden(
            input="Username: alex_w. I would like a refund for my mechanical_keyboard.",
            expected_output="A refund ticket for $110 was issued successfully for the mechanical keyboard.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "alex_w"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "alex_w", "items": [{"name": "mechanical_keyboard"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "alex_w", "refund_amount": 110}),
            ]
        ),
        Golden(
            input="I am user126, I would like a refund for the water_bottle",
            expected_output="No refund will be issued because the water bottle was purchased outside the 30-day refund guideline.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user126"}),
                ToolCall(name="get_today_date", input_parameters={}),
            ]
        ),
        Golden(
            input="Hi, I'm michael_b. I'd like a refund on the smart_watch.",
            expected_output="No refund can be issued because the smart watch has an invalid future purchase date.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "michael_b"}),
                ToolCall(name="get_today_date", input_parameters={}),
            ]
        ),

        # CATEGORY 3: PARTIAL ELIGIBILITY & MIXED STATES
       
        Golden(
            input="I am user126, I would like a refund for the backpack and water_bottle",
            expected_output="A refund ticket for $45 has been issued successfully for the backpack. The water bottle is not eligible because it is outside the 30-day refund policy.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user126"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "user126", "items": [{"name": "backpack"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "user126", "refund_amount": 45}),
            ]
        ),
        Golden(
            input="My name is elena_r. I want a refund for the drawing_tablet and the stylus_pen.",
            expected_output="A refund ticket for $30 has been issued for the stylus pen. The drawing tablet is not eligible because it exceeds the 30-day return window.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "elena_r"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "elena_r", "items": [{"name": "stylus_pen"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "elena_r", "refund_amount": 30}),
            ]
        ),
        Golden(
            input="Hey, I am alex_w. I need a refund for the mechanical_keyboard and the keycap_set.",
            expected_output="A refund ticket for $110 was issued for the mechanical keyboard. The keycap set is ineligible as it was purchased outside the 30-day policy.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "alex_w"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "alex_w", "items": [{"name": "mechanical_keyboard"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "alex_w", "refund_amount": 110}),
            ]
        ),
        Golden(
            input="I'm marcus_t. Can you refund my running_shoes, yoga_mat, and water_bottle?",
            expected_output="A refund ticket for $125 has been issued for the running shoes ($90) and yoga mat ($35). The water bottle is outside the 30-day window and cannot be refunded.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "marcus_t"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "marcus_t", "items": [{"name": "running_shoes"}, {"name": "yoga_mat"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "marcus_t", "refund_amount": 125}),
            ]
        ),
        Golden(
            input="Hi, chloe_d here. I want to return my backpack and also an umbrella.",
            expected_output="A refund ticket for $55 has been issued for the backpack. The umbrella cannot be refunded because it was never purchased on this account.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "chloe_d"}),
                ToolCall(name="get_today_date", input_parameters={}),
                ToolCall(name="calculate_right_refund", input_parameters={"user": "chloe_d", "items": [{"name": "backpack"}]}),
                ToolCall(name="issue_refund_ticket", input_parameters={"user": "chloe_d", "refund_amount": 55}),
            ]
        ),

        # CATEGORY 4: INFORMATIONAL INQUIRIES (NO REFUND TICKET ISSUED)
        Golden(
            input="I am user123, I would like no refund, I just want to know what I purchased",
            expected_output="Here is your purchase history: book and pen. No refund tickets were issued.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user123"}),
            ]
        ),
        Golden(
            input="Hi, I'm sarah_m. Can you tell me what items are currently in my order history?",
            expected_output="Your order history contains a laptop stand and a wireless mouse. No refund ticket has been created.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "sarah_m"}),
            ]
        ),
        Golden(
            input="Hey, marcus_t here. Just checking what I bought last month, not looking for a return.",
            expected_output="Your purchase history shows running shoes, yoga mat, and water bottle. No refund was requested or issued.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "marcus_t"}),
            ]
        ),
        Golden(
            input="I am david_k. Did I purchase a travel mug from your store?",
            expected_output="Yes, you purchased a travel mug for $15 on 2026-9-25. No refund was issued.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "david_k"}),
            ]
        ),

        # CATEGORY 5: NEGATIVE, GUARDRAIL & UNPURCHASED ITEM SCENARIOS
        Golden(
            input="I am user999, I would like a refund for the book",
            expected_output="The username user999 was not valid. Please provide a valid username to proceed.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user999"}),
            ]
        ),
        Golden(
            input="Hello, my username is ghost_user and I need my money back for an order.",
            expected_output="The username ghost_user is not valid. Please provide a registered username.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "ghost_user"}),
            ]
        ),
        Golden(
            input="I am user126, I would like a refund for the sneakers",
            expected_output="No refund can be issued because sneakers were not purchased under your account.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "user126"}),
            ]
        ),
        Golden(
            input="Hi, I'm james_h. Can I get a refund on the wireless_headphones?",
            expected_output="No refund can be issued because wireless headphones were not found in your purchase history.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "james_h"}),
            ]
        ),
        Golden(
            input="I am james_h. I'd like a refund for the gaming_chair please.",
            expected_output="No refund can be issued because the gaming chair was purchased on 2026-7-15, which is outside the 30-day refund window.",
            expected_tools=[
                ToolCall(name="get_user_purchase_history", input_parameters={"user": "james_h"}),
                ToolCall(name="get_today_date", input_parameters={}),
            ]
        ),
    ]
)
