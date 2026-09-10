-- ============================================
-- PERFORMANCE INDEXES
-- ============================================

-- User Accounts Indexes
CREATE INDEX IF NOT EXISTS idx_user_email ON user_accounts(email);
CREATE INDEX IF NOT EXISTS idx_user_location ON user_accounts(city, state);
CREATE INDEX IF NOT EXISTS idx_user_active ON user_accounts(is_active) WHERE is_active = true;

-- Marketplace Items Indexes
CREATE INDEX IF NOT EXISTS idx_item_seller ON marketplace_items(seller_id);
CREATE INDEX IF NOT EXISTS idx_item_category ON marketplace_items(category) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_item_location ON marketplace_items(city, state) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_item_price ON marketplace_items(price) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_item_created ON marketplace_items(created_at DESC);

-- Full-text search on title
CREATE INDEX IF NOT EXISTS idx_item_title_search 
ON marketplace_items USING gin(to_tsvector('english', title));

-- Item Images Indexes
CREATE INDEX IF NOT EXISTS idx_image_item ON item_images(item_id);
CREATE INDEX IF NOT EXISTS idx_image_thumbnail ON item_images(item_id) WHERE is_thumbnail = true;

-- Interactions Indexes
CREATE INDEX IF NOT EXISTS idx_interactions_user ON item_interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_item ON item_interactions(item_id);
CREATE INDEX IF NOT EXISTS idx_interactions_type ON item_interactions(event_type);

-- Messages Indexes
CREATE INDEX IF NOT EXISTS idx_message_receiver ON marketplace_messages(receiver_id, is_read);
CREATE INDEX IF NOT EXISTS idx_message_sender ON marketplace_messages(sender_id);

-- Saved Items Indexes
CREATE INDEX IF NOT EXISTS idx_saved_user ON item_saved(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_item ON item_saved(item_id);

-- User Activity Indexes
CREATE INDEX IF NOT EXISTS idx_activity_user ON user_activity(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_item ON user_activity(item_id);
CREATE INDEX IF NOT EXISTS idx_activity_type ON user_activity(activity_type);
CREATE INDEX IF NOT EXISTS idx_activity_created ON user_activity(created_at DESC);

COMMIT;
