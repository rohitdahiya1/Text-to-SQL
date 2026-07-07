-- ============================================================
-- E-Commerce Seed Schema for Text-to-SQL Testing
-- Run this directly in Supabase SQL Editor
-- 10 interlinked tables with realistic data (10-15 rows each)
-- ============================================================

-- ============================================================
-- Drop tables in reverse dependency order (safe re-run)
-- ============================================================
DROP TABLE IF EXISTS reviews CASCADE;
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS product_inventory CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS categories CASCADE;
DROP TABLE IF EXISTS addresses CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS regions CASCADE;

-- ============================================================
-- 1. regions
-- Lookup table for geographic regions
-- ============================================================
CREATE TABLE regions (
    region_id   SERIAL PRIMARY KEY,
    region_name VARCHAR(100) NOT NULL,
    country     VARCHAR(100) NOT NULL DEFAULT 'India'
);

INSERT INTO regions (region_name, country) VALUES
    ('North',     'India'),
    ('South',     'India'),
    ('East',      'India'),
    ('West',      'India'),
    ('Central',   'India'),
    ('Northeast', 'India');

-- ============================================================
-- 2. customers
-- Core customer master table
-- ============================================================
CREATE TABLE customers (
    customer_id   SERIAL PRIMARY KEY,
    full_name     VARCHAR(150) NOT NULL,
    email         VARCHAR(150) UNIQUE NOT NULL,
    phone         VARCHAR(20),
    gender        VARCHAR(10) CHECK (gender IN ('Male', 'Female', 'Other')),
    date_of_birth DATE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO customers (full_name, email, phone, gender, date_of_birth, created_at) VALUES
    ('Rohit Sharma',     'rohit.sharma@email.com',   '9876543210', 'Male',   '1990-05-14', '2022-01-10 10:00:00+05:30'),
    ('Priya Nair',       'priya.nair@email.com',     '9123456780', 'Female', '1992-08-22', '2022-03-15 11:30:00+05:30'),
    ('Arjun Mehta',      'arjun.mehta@email.com',    '9988776655', 'Male',   '1988-12-01', '2022-06-01 09:00:00+05:30'),
    ('Sneha Patel',      'sneha.patel@email.com',    '9871234560', 'Female', '1995-03-30', '2023-01-20 14:00:00+05:30'),
    ('Vikram Singh',     'vikram.singh@email.com',   '9001122334', 'Male',   '1985-07-19', '2023-02-11 08:00:00+05:30'),
    ('Ananya Bose',      'ananya.bose@email.com',    '9765432109', 'Female', '1993-11-05', '2023-03-05 16:00:00+05:30'),
    ('Karan Verma',      'karan.verma@email.com',    '9654321098', 'Male',   '1991-09-23', '2023-05-18 10:00:00+05:30'),
    ('Meena Iyer',       'meena.iyer@email.com',     '9543210987', 'Female', '1989-02-14', '2023-07-22 13:00:00+05:30'),
    ('Rajesh Kumar',     'rajesh.kumar@email.com',   '9432109876', 'Male',   '1987-04-08', '2023-09-01 09:30:00+05:30'),
    ('Divya Reddy',      'divya.reddy@email.com',    '9321098765', 'Female', '1996-06-17', '2024-01-05 11:00:00+05:30'),
    ('Aditya Joshi',     'aditya.joshi@email.com',   '9210987654', 'Male',   '1994-10-29', '2024-02-14 15:00:00+05:30'),
    ('Pooja Desai',      'pooja.desai@email.com',    '9109876543', 'Female', '1997-01-11', '2024-03-20 12:00:00+05:30');

-- ============================================================
-- 3. addresses
-- Customer delivery/billing addresses (one customer can have many)
-- ============================================================
CREATE TABLE addresses (
    address_id   SERIAL PRIMARY KEY,
    customer_id  INT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    region_id    INT NOT NULL REFERENCES regions(region_id),
    address_line VARCHAR(255) NOT NULL,
    city         VARCHAR(100) NOT NULL,
    state        VARCHAR(100) NOT NULL,
    pincode      VARCHAR(10) NOT NULL,
    address_type VARCHAR(20) CHECK (address_type IN ('Home', 'Work', 'Other')) DEFAULT 'Home',
    is_default   BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO addresses (customer_id, region_id, address_line, city, state, pincode, address_type, is_default) VALUES
    (1,  1, '12 Connaught Place',      'New Delhi',    'Delhi',             '110001', 'Home',  TRUE),
    (2,  2, '45 Anna Salai',           'Chennai',      'Tamil Nadu',        '600002', 'Home',  TRUE),
    (3,  3, '7 Park Street',           'Kolkata',      'West Bengal',       '700016', 'Home',  TRUE),
    (4,  4, '88 Linking Road',         'Mumbai',       'Maharashtra',       '400050', 'Work',  TRUE),
    (5,  1, '23 Rajpur Road',          'Dehradun',     'Uttarakhand',       '248001', 'Home',  TRUE),
    (6,  3, '19 Camac Street',         'Kolkata',      'West Bengal',       '700017', 'Home',  TRUE),
    (7,  4, '56 Bandra Kurla Complex', 'Mumbai',       'Maharashtra',       '400051', 'Work',  TRUE),
    (8,  2, '33 Brigade Road',         'Bengaluru',    'Karnataka',         '560001', 'Home',  TRUE),
    (9,  5, '11 MG Road',              'Bhopal',       'Madhya Pradesh',    '462001', 'Home',  TRUE),
    (10, 2, '78 Jubilee Hills',        'Hyderabad',    'Telangana',         '500033', 'Home',  TRUE),
    (11, 4, '22 FC Road',              'Pune',         'Maharashtra',       '411004', 'Home',  TRUE),
    (12, 1, '5 Sector 17',             'Chandigarh',   'Punjab',            '160017', 'Home',  TRUE),
    (1,  4, '101 Nariman Point',       'Mumbai',       'Maharashtra',       '400021', 'Work',  FALSE);

-- ============================================================
-- 4. categories
-- Product category hierarchy (supports parent category)
-- ============================================================
CREATE TABLE categories (
    category_id   SERIAL PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL,
    parent_id     INT REFERENCES categories(category_id),
    description   TEXT
);

INSERT INTO categories (category_name, parent_id, description) VALUES
    ('Electronics',      NULL, 'All electronic devices and accessories'),
    ('Clothing',         NULL, 'Apparel for men, women, and children'),
    ('Home & Kitchen',   NULL, 'Furniture, cookware, and home decor'),
    ('Sports',           NULL, 'Sports equipment and fitness gear'),
    ('Books',            NULL, 'Physical and digital books'),
    ('Mobile Phones',    1,    'Smartphones and feature phones'),
    ('Laptops',          1,    'Notebooks and ultrabooks'),
    ('Men Clothing',     2,    'Shirts, trousers, and jackets for men'),
    ('Women Clothing',   2,    'Dresses, sarees, and tops for women'),
    ('Kitchen Appliances', 3,  'Mixers, ovens, and cookers');

-- ============================================================
-- 5. products
-- Product catalog linked to categories
-- ============================================================
CREATE TABLE products (
    product_id    SERIAL PRIMARY KEY,
    category_id   INT NOT NULL REFERENCES categories(category_id),
    product_name  VARCHAR(200) NOT NULL,
    brand         VARCHAR(100),
    sku           VARCHAR(50) UNIQUE NOT NULL,
    unit_price    NUMERIC(10, 2) NOT NULL,
    cost_price    NUMERIC(10, 2) NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO products (category_id, product_name, brand, sku, unit_price, cost_price) VALUES
    (6,  'iPhone 15 Pro 256GB',           'Apple',    'APL-IP15P-256',  129999.00,  95000.00),
    (6,  'Samsung Galaxy S24 Ultra',      'Samsung',  'SAM-S24U-512',   124999.00,  91000.00),
    (7,  'Dell XPS 15 Laptop',            'Dell',     'DEL-XPS15-I7',    89999.00,  68000.00),
    (7,  'MacBook Air M3',                'Apple',    'APL-MBA-M3-16',  114999.00,  87000.00),
    (8,  'Men Slim Fit Shirt - Blue',     'Arrow',    'ARW-SFS-BLU-L',    1299.00,    600.00),
    (8,  'Men Chino Trousers - Khaki',    'Lee',      'LEE-CHN-KHK-32',   1899.00,    850.00),
    (9,  'Women Floral Kurti - Red',      'Biba',     'BIB-FKR-RED-M',    1499.00,    700.00),
    (9,  'Women Formal Blazer - Black',   'Van Heusen','VH-FBL-BLK-S',    3499.00,   1800.00),
    (10, 'Instant Pot Duo 7-in-1',        'Instant',  'INS-POT-DUO-6L',   7999.00,   4500.00),
    (10, 'Philips Air Fryer HD9216',      'Philips',  'PHL-AF-HD9216',    5499.00,   3200.00),
    (4,  'Yonex Badminton Racket',        'Yonex',    'YNX-BR-VT-10',     2199.00,   1100.00),
    (5,  'Atomic Habits - James Clear',   'Penguin',  'PEN-AH-JC-PB',      499.00,    180.00),
    (6,  'OnePlus 12 5G 256GB',           'OnePlus',  'OP-12-5G-256',    64999.00,  48000.00);

-- ============================================================
-- 6. product_inventory
-- Stock levels per product (separated for normalization)
-- ============================================================
CREATE TABLE product_inventory (
    inventory_id      SERIAL PRIMARY KEY,
    product_id        INT NOT NULL UNIQUE REFERENCES products(product_id),
    quantity_in_stock INT NOT NULL DEFAULT 0,
    reorder_level     INT NOT NULL DEFAULT 10,
    last_restocked_at TIMESTAMPTZ
);

INSERT INTO product_inventory (product_id, quantity_in_stock, reorder_level, last_restocked_at) VALUES
    (1,  45,  10, '2024-10-01 10:00:00+05:30'),
    (2,  30,  10, '2024-10-05 10:00:00+05:30'),
    (3,  20,  5,  '2024-09-15 10:00:00+05:30'),
    (4,  15,  5,  '2024-10-10 10:00:00+05:30'),
    (5,  200, 30, '2024-09-20 10:00:00+05:30'),
    (6,  180, 30, '2024-09-22 10:00:00+05:30'),
    (7,  220, 30, '2024-09-25 10:00:00+05:30'),
    (8,  95,  20, '2024-09-28 10:00:00+05:30'),
    (9,  60,  15, '2024-10-02 10:00:00+05:30'),
    (10, 75,  15, '2024-10-03 10:00:00+05:30'),
    (11, 110, 20, '2024-09-18 10:00:00+05:30'),
    (12, 300, 50, '2024-10-08 10:00:00+05:30'),
    (13, 55,  10, '2024-10-12 10:00:00+05:30');

-- ============================================================
-- 7. orders
-- Order header — one row per order
-- ============================================================
CREATE TABLE orders (
    order_id         SERIAL PRIMARY KEY,
    customer_id      INT NOT NULL REFERENCES customers(customer_id),
    address_id       INT NOT NULL REFERENCES addresses(address_id),
    order_status     VARCHAR(30) CHECK (order_status IN ('pending','confirmed','shipped','delivered','cancelled','returned')) NOT NULL DEFAULT 'pending',
    total_amount     NUMERIC(12, 2) NOT NULL,
    discount_amount  NUMERIC(10, 2) NOT NULL DEFAULT 0,
    shipping_charge  NUMERIC(8, 2) NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at     TIMESTAMPTZ
);

INSERT INTO orders (customer_id, address_id, order_status, total_amount, discount_amount, shipping_charge, created_at, delivered_at) VALUES
    (1,  1,  'delivered',  131298.00,  2000.00, 0.00,   '2024-01-15 10:00:00+05:30', '2024-01-20 15:00:00+05:30'),
    (2,  2,  'delivered',    7999.00,   500.00, 0.00,   '2024-02-10 11:00:00+05:30', '2024-02-14 12:00:00+05:30'),
    (3,  3,  'delivered',   91298.00,  1500.00, 0.00,   '2024-03-05 09:00:00+05:30', '2024-03-10 11:00:00+05:30'),
    (4,  4,  'shipped',    124999.00,  3000.00, 0.00,   '2024-04-18 14:00:00+05:30', NULL),
    (5,  5,  'delivered',    3198.00,   200.00, 49.00,  '2024-05-01 08:00:00+05:30', '2024-05-06 10:00:00+05:30'),
    (6,  6,  'cancelled',   65498.00,  1000.00, 0.00,   '2024-05-20 16:00:00+05:30', NULL),
    (7,  7,  'delivered',  116298.00,  2500.00, 0.00,   '2024-06-11 10:00:00+05:30', '2024-06-16 14:00:00+05:30'),
    (8,  8,  'delivered',    5998.00,   300.00, 99.00,  '2024-07-04 13:00:00+05:30', '2024-07-09 11:00:00+05:30'),
    (9,  9,  'returned',    2199.00,     0.00, 49.00,  '2024-07-22 09:30:00+05:30', NULL),
    (10, 10, 'delivered',  130498.00,  4000.00, 0.00,   '2024-08-15 11:00:00+05:30', '2024-08-20 16:00:00+05:30'),
    (11, 11, 'confirmed',    1499.00,   100.00, 49.00,  '2024-09-01 15:00:00+05:30', NULL),
    (12, 12, 'delivered',    8498.00,   500.00, 0.00,   '2024-09-18 12:00:00+05:30', '2024-09-23 13:00:00+05:30'),
    (1,  13, 'delivered',  114999.00,  5000.00, 0.00,   '2024-10-05 10:00:00+05:30', '2024-10-10 15:00:00+05:30');

-- ============================================================
-- 8. order_items
-- Line items per order (bridge: orders ↔ products)
-- ============================================================
CREATE TABLE order_items (
    order_item_id SERIAL PRIMARY KEY,
    order_id      INT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id    INT NOT NULL REFERENCES products(product_id),
    quantity      INT NOT NULL CHECK (quantity > 0),
    unit_price    NUMERIC(10, 2) NOT NULL,
    subtotal      NUMERIC(12, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED
);

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1,  1,  1, 129999.00),
    (1,  5,  1,   1299.00),
    (2,  9,  1,   7999.00),
    (3,  3,  1,  89999.00),
    (3,  11, 1,   2199.00) ,
    (4,  2,  1, 124999.00),
    (5,  5,  1,   1299.00),
    (5,  6,  1,   1899.00),
    (6,  13, 1,  64999.00),
    (6,  12, 1,    499.00),
    (7,  4,  1, 114999.00),
    (7,  8,  1,   3499.00) ,
    (8,  10, 1,   5499.00),
    (8,  12, 1,    499.00),
    (9,  11, 1,   2199.00),
    (10, 1,  1, 129999.00),
    (10, 7,  1,   1499.00),
    (11, 7,  1,   1499.00),
    (12, 9,  1,   7999.00),
    (12, 12, 2,    499.00),
    (13, 4,  1, 114999.00);

-- ============================================================
-- 9. payments
-- Payment record per order (one-to-one in this model)
-- ============================================================
CREATE TABLE payments (
    payment_id     SERIAL PRIMARY KEY,
    order_id       INT NOT NULL UNIQUE REFERENCES orders(order_id),
    payment_method VARCHAR(30) CHECK (payment_method IN ('UPI','Credit Card','Debit Card','Net Banking','COD','Wallet')) NOT NULL,
    payment_status VARCHAR(20) CHECK (payment_status IN ('pending','success','failed','refunded')) NOT NULL DEFAULT 'pending',
    paid_amount    NUMERIC(12, 2) NOT NULL,
    transaction_id VARCHAR(100),
    paid_at        TIMESTAMPTZ
);

INSERT INTO payments (order_id, payment_method, payment_status, paid_amount, transaction_id, paid_at) VALUES
    (1,  'Credit Card', 'success',  131298.00, 'TXN10000001', '2024-01-15 10:05:00+05:30'),
    (2,  'UPI',         'success',    7999.00, 'TXN10000002', '2024-02-10 11:02:00+05:30'),
    (3,  'Net Banking', 'success',   91298.00, 'TXN10000003', '2024-03-05 09:03:00+05:30'),
    (4,  'Credit Card', 'success',  124999.00, 'TXN10000004', '2024-04-18 14:01:00+05:30'),
    (5,  'UPI',         'success',    3198.00, 'TXN10000005', '2024-05-01 08:02:00+05:30'),
    (6,  'Debit Card',  'refunded',  65498.00, 'TXN10000006', '2024-05-20 16:05:00+05:30'),
    (7,  'Credit Card', 'success',  116298.00, 'TXN10000007', '2024-06-11 10:03:00+05:30'),
    (8,  'Wallet',      'success',    5998.00, 'TXN10000008', '2024-07-04 13:01:00+05:30'),
    (9,  'COD',         'refunded',   2199.00, 'TXN10000009', '2024-07-22 09:35:00+05:30'),
    (10, 'Credit Card', 'success',  130498.00, 'TXN10000010', '2024-08-15 11:02:00+05:30'),
    (11, 'UPI',         'pending',    1499.00, NULL,           NULL),
    (12, 'UPI',         'success',    8498.00, 'TXN10000012', '2024-09-18 12:05:00+05:30'),
    (13, 'Credit Card', 'success',  114999.00, 'TXN10000013', '2024-10-05 10:04:00+05:30');

-- ============================================================
-- 10. reviews
-- Product reviews left by customers post-purchase
-- ============================================================
CREATE TABLE reviews (
    review_id   SERIAL PRIMARY KEY,
    product_id  INT NOT NULL REFERENCES products(product_id),
    customer_id INT NOT NULL REFERENCES customers(customer_id),
    order_id    INT NOT NULL REFERENCES orders(order_id),
    rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title       VARCHAR(200),
    body        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, customer_id, order_id)
);

INSERT INTO reviews (product_id, customer_id, order_id, rating, title, body, created_at) VALUES
    (1,  1,  1,  5, 'Incredible phone',         'Best smartphone I have ever used. Camera is top-notch.',             '2024-01-22 10:00:00+05:30'),
    (9,  2,  2,  4, 'Great pressure cooker',    'Cooks quickly and evenly. Slightly difficult to clean.',             '2024-02-16 11:00:00+05:30'),
    (3,  3,  3,  5, 'Brilliant laptop',          'Blazing fast performance for development work.',                     '2024-03-12 09:00:00+05:30'),
    (11, 3,  3,  3, 'Average racket',            'Decent quality but expected more for the price.',                   '2024-03-13 09:30:00+05:30'),
    (5,  5,  5,  4, 'Good fit and quality',      'Comfortable shirt. Colour is exactly as shown.',                    '2024-05-08 10:00:00+05:30'),
    (4,  7,  7,  5, 'MacBook is a beast',        'M3 chip handles everything effortlessly. Battery life is amazing.',  '2024-06-18 14:00:00+05:30'),
    (10, 8,  8,  4, 'Healthy cooking made easy', 'Air fryer works well. Timer dial feels a bit cheap.',               '2024-07-11 13:00:00+05:30'),
    (12, 8,  8,  5, 'Life-changing book',        'Atomic Habits has genuinely improved my daily routine.',             '2024-07-12 13:30:00+05:30'),
    (1,  10, 10, 5, 'Worth every rupee',         'Pro camera system is unbelievable. Fast and fluid UI.',             '2024-08-22 11:00:00+05:30'),
    (7,  10, 10, 4, 'Pretty kurti',              'Fabric quality is good. Stitching is neat.',                        '2024-08-23 11:30:00+05:30'),
    (9,  12, 12, 5, 'Best kitchen buy',          'Instant Pot is a game changer for meal prep.',                      '2024-09-25 12:00:00+05:30'),
    (4,  1,  13, 5, 'MacBook M3 — perfection',  'Switched from Windows. No regrets. Runs everything I need.',        '2024-10-12 10:00:00+05:30');


-- ============================================================
-- Useful indexes for query performance
-- ============================================================
CREATE INDEX idx_orders_customer_id       ON orders(customer_id);
CREATE INDEX idx_orders_status            ON orders(order_status);
CREATE INDEX idx_orders_created_at        ON orders(created_at);
CREATE INDEX idx_order_items_order_id     ON order_items(order_id);
CREATE INDEX idx_order_items_product_id   ON order_items(product_id);
CREATE INDEX idx_payments_order_id        ON payments(order_id);
CREATE INDEX idx_reviews_product_id       ON reviews(product_id);
CREATE INDEX idx_reviews_customer_id      ON reviews(customer_id);
CREATE INDEX idx_products_category_id     ON products(category_id);
CREATE INDEX idx_addresses_customer_id    ON addresses(customer_id);
CREATE INDEX idx_addresses_region_id      ON addresses(region_id);