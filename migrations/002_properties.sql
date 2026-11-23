-- Properties for sale and their photos/videos. Prices are in toman (like customer budgets).

CREATE TABLE properties (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    property_type TEXT NOT NULL
                  CHECK (property_type IN ('land', 'apartment', 'villa', 'commercial', 'garden', 'other')),
    area_m2       INTEGER NOT NULL CHECK (area_m2 > 0),
    location      TEXT NOT NULL,
    price         INTEGER NOT NULL CHECK (price > 0),
    status        TEXT NOT NULL DEFAULT 'available'
                  CHECK (status IN ('available', 'reserved', 'sold')),
    notes         TEXT,
    created_by    INTEGER NOT NULL REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_properties_search ON properties(status, property_type);

-- Photos and videos are stored by Telegram file_id only (the files stay on Telegram's servers).
CREATE TABLE property_media (
    id              INTEGER PRIMARY KEY,
    property_id     INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('photo', 'video')),
    file_id         TEXT NOT NULL,
    file_unique_id  TEXT,
    media_group_id  TEXT,
    caption         TEXT,
    added_by        INTEGER NOT NULL REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_property_media_property ON property_media(property_id);
CREATE UNIQUE INDEX idx_property_media_unique ON property_media(property_id, file_unique_id);
