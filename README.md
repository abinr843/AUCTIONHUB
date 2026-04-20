# Online Auction Platform

## 1. Project Abstract
Welcome to the Custom Online Auction Platform! This application is a high-performance, feature-rich web marketplace built around a **Django 5.1.4 (Python)** backend and a **raw MySQL** database integration. 

### Unique Architectural Choices
* **Raw SQL over Django ORM:** To maximize query performance and tight transaction control, this project bypasses the standard `models.py` approach. Instead, nearly all database interactions are written via explicitly parameterized `connection.cursor()` queries wrapped in `transaction.atomic()` contexts.
* **Intelligent Chatbot Integration:** Embedded inside the core routing is an advanced NLP Chatbot that utilizes an ensemble of **BERT** (Intent Classification), **T5** (Fallback Generation), NLTK, and spaCy. It handles fuzzy pattern matching via an expansive `intents.json` and supports an iterative Human-in-the-Loop admin mechanism for answering unknown queries.
* **Advanced Bidding Ecosystem:** It inherently natively supports standard auctions, sealed-bid mechanisms, and buy-it-now/offers, backed by a robust internal wallet mechanism.
* **Comprehensive Notification Stack:** Dynamic, real-time in-app and email notifications using Django's SMTP backend.

---

## 2. Infrastructure Automation (`scheduler.py`)
This system runs an extensive background cron-like asynchronous automation logic handler via `scheduler.py` to seamlessly orchestrate the lifecycle of auctions, bids, and user states.

### Core Automation Pipelines:
* **Winner Selection (Regular & Sealed Bids):** The engine constantly monitors ended auctions and selection-date thresholds. It automatically computes the highest bids, validates them against reserve prices, binds winners into final `Orders`, and issues victory/loss notification blasts.
* **Invoice Generation Strategy:** The system automatically sweeps pending orders and emits custom UUID `Invoices` to the respective buyers, attaching initial pending statuses. 
* **Overdue Analytics & Late Fees:** Periodically sweeps current unpaid invoices against their due dates. If an invoice crosses into an `Overdue` state, a recursive 5% penalty late fee is mathematically appended to the order and an overdue alert is fired.
* **Premium User Lifecycle Management:** Monitors the `premium_end_date` of active VIP users. It fires automated warning emails 2 days prior to expiration. Once expired, it downgrades the user automatically and shuts off platform perks, informing them of the structural change.
* **Global Auction Sync:** Triggers system blasts whenever unseen/un-notified auctions are detected.

---

## 3. Developer Environment Setup (Ignored Files & Secrets)
Because this application contains strict security footprints, massive Deep Learning weights, and live transactional user logs, we actively ignore various internal mechanisms via `.gitignore`. 

**If you are cloning this repository, you must manually construct the following elements:**

### A. Environment Config (`settings.py` / `.env`)
* By default, the `online_auction/settings.py` file is ignored since it contains hardcoded configurations such as your secret keys, MySQL root passwords (`Mysql@123`), and your SMTP app credentials.
* **To Fix:** Create a local `settings.py` file mapped to a `sqlite3` or local MySQL server instance, and ensure the `SECRET_KEY` is securely supplied.

### B. Database Requirements
* The base SQL dumps (`auctionss.sql`) are ignored as they might contain active PII user logs. 
* **To Fix:** You must create an empty MySQL database named `auctions` on `localhost:3306` with user `root` and generate the required schema structures.

**System Database Tables:**
The raw MySQL architecture relies on the following 28 foundational tables:
* `auction_images`
* `auctions`
* `bank_cards`
* `bids`
* `categories`
* `django_session`
* `feedback`
* `feedback_replies`
* `fund_distribution`
* `invoices`
* `membership_plans`
* `messages`
* `notifications`
* `offers`
* `orders`
* `payment_details`
* `platform_commission`
* `premium_users`
* `reported_users`
* `reviews`
* `sealed_bid_details`
* `seller_payouts`
* `shipping_details`
* `user_activity`
* `user_otp`
* `users`
* `wallets`
* `watchlist`

### C. File Storage & Media
* User-uploaded media and cached profiles are ignored.
* **To Fix:** Simply recreate the `majorproject/online_auction/media/` directory to satisfy Django's `MEDIA_ROOT`. 

### D. Artificial Intelligence Models
* Pushing multi-gigabyte models into Git is forbidden. All `/core/chatbot_bert_model/` and `/core/chatbot_t5_model/` paths are ignored, alongside `vectorizer.pkl`.
* **To Fix:** You must generate, fine-tune, or pull the PyTorch weights (`.bin` / `.safetensors`) and tokenizer assets manually into those paths or use the fallback logic scripts (`train_chatbot.py`).

### E. JSON Transaction Logs
* User histories and chatbot sessions are highly dynamic and ignored.
* **To Fix:** The bot has a self-healing function. When the first `POST` hits `/chatbot_response/`, it will safely regenerate empty states for `users.json`, `sessions.json`, `conversation_history.json`, `answered_questions.json`, and `new_questions.json`.
