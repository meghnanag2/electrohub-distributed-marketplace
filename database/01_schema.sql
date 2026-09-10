-- ============================================
-- ELECTROHUB MARKETPLACE DATABASE SCHEMA
-- ============================================

-- User Accounts Table
CREATE TABLE IF NOT EXISTS user_accounts (
    account_id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    profile_picture TEXT DEFAULT 'https://ui-avatars.com/api/?name=User&size=200',
    bio TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    is_verified BOOLEAN DEFAULT false
);

-- Marketplace Items Table
CREATE TABLE IF NOT EXISTS marketplace_items (
    item_id SERIAL PRIMARY KEY,
    seller_id VARCHAR(255) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) DEFAULT 'Electronics',
    price DECIMAL(10,2) NOT NULL,
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code INT,
    condition VARCHAR(50) DEFAULT 'new',
    views_count INT DEFAULT 0,
    saves_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    FOREIGN KEY (seller_id) REFERENCES user_accounts(user_id) ON DELETE CASCADE
);

-- Item Images Table
CREATE TABLE IF NOT EXISTS item_images (
    image_id SERIAL PRIMARY KEY,
    item_id INT NOT NULL,
    image_url TEXT NOT NULL,
    is_thumbnail BOOLEAN DEFAULT false,
    upload_order INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES marketplace_items(item_id) ON DELETE CASCADE
);

-- User Interactions Table
CREATE TABLE IF NOT EXISTS item_interactions (
    interaction_id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    item_id INT NOT NULL,
    event_type VARCHAR(20) NOT NULL,  -- 'view', 'save', 'message', 'click'
    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    session_id VARCHAR(255),
    FOREIGN KEY (user_id) REFERENCES user_accounts(user_id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES marketplace_items(item_id) ON DELETE CASCADE
);

-- Messages Table
CREATE TABLE IF NOT EXISTS marketplace_messages (
    message_id BIGSERIAL PRIMARY KEY,
    sender_id VARCHAR(255) NOT NULL,
    receiver_id VARCHAR(255) NOT NULL,
    item_id INT NOT NULL,
    message_text TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN DEFAULT false,
    FOREIGN KEY (sender_id) REFERENCES user_accounts(user_id) ON DELETE CASCADE,
    FOREIGN KEY (receiver_id) REFERENCES user_accounts(user_id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES marketplace_items(item_id) ON DELETE CASCADE
);

-- Saved Items Table
CREATE TABLE IF NOT EXISTS item_saved (
    save_id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    item_id INT NOT NULL,
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_accounts(user_id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES marketplace_items(item_id) ON DELETE CASCADE,
    UNIQUE(user_id, item_id)
);

-- User Activity Log Table
CREATE TABLE IF NOT EXISTS user_activity (
    activity_id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    item_id INT,
    activity_type VARCHAR(50) NOT NULL,
    action VARCHAR(255),
    activity_metadata TEXT,
    session_id VARCHAR(255),
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_accounts(user_id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES marketplace_items(item_id) ON DELETE SET NULL
);

COMMIT;
