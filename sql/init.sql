-- ============================================
-- MultiAgent-Search - 数据库初始化脚本
-- 首次启动 MySQL 容器时自动执行
-- ============================================

CREATE DATABASE IF NOT EXISTS deep_search
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE deep_search;

-- 商品表
CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sku VARCHAR(32) NOT NULL COMMENT '商品编码',
    product_name VARCHAR(128) NOT NULL COMMENT '商品名称',
    category VARCHAR(64) COMMENT '商品品类',
    price DECIMAL(10, 2) NOT NULL COMMENT '销售价格',
    stock INT NOT NULL DEFAULT 0 COMMENT '库存数量',
    status VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT '商品状态',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    CONSTRAINT chk_products_price CHECK (price >= 0),
    CONSTRAINT chk_products_stock CHECK (stock >= 0),
    CONSTRAINT chk_products_status CHECK (status IN ('active', 'inactive', 'sold_out')),
    UNIQUE KEY uk_products_sku (sku),
    INDEX idx_products_name (product_name),
    INDEX idx_products_status (status),
    INDEX idx_products_category_status (category, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品表';

-- 客户表
CREATE TABLE IF NOT EXISTS customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_name VARCHAR(64) NOT NULL COMMENT '客户名称',
    phone VARCHAR(20) COMMENT '手机号码',
    email VARCHAR(128) COMMENT '电子邮箱',
    level VARCHAR(16) NOT NULL DEFAULT 'normal' COMMENT '客户等级',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    CONSTRAINT chk_customers_level CHECK (level IN ('normal', 'vip')),
    UNIQUE KEY uk_customers_phone (phone),
    UNIQUE KEY uk_customers_email (email),
    INDEX idx_customers_name (customer_name),
    INDEX idx_customers_level_created_at (level, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客户表';

-- 示例：电商订单表（供 Agent 演示用）
CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_no VARCHAR(32) NOT NULL COMMENT '订单号',
    product_name VARCHAR(128) NOT NULL COMMENT '商品名称',
    category VARCHAR(64) COMMENT '品类',
    price DECIMAL(10, 2) NOT NULL COMMENT '单价',
    quantity INT NOT NULL DEFAULT 1 COMMENT '数量',
    total_amount DECIMAL(10, 2) NOT NULL COMMENT '总金额',
    customer_name VARCHAR(64) COMMENT '客户名称',
    status VARCHAR(16) NOT NULL DEFAULT 'completed' COMMENT '订单状态',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    CONSTRAINT chk_orders_price CHECK (price >= 0),
    CONSTRAINT chk_orders_quantity CHECK (quantity > 0),
    CONSTRAINT chk_orders_total_amount CHECK (total_amount >= 0),
    CONSTRAINT chk_orders_status CHECK (status IN ('pending', 'paid', 'completed', 'cancelled', 'refunded')),
    UNIQUE KEY uk_orders_order_no (order_no),
    INDEX idx_created_at (created_at),
    INDEX idx_orders_customer_name (customer_name),
    INDEX idx_orders_product_name (product_name),
    INDEX idx_orders_category_created_at (category, created_at),
    INDEX idx_orders_status_created_at (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单表';

-- 插入商品示例数据
INSERT INTO products (sku, product_name, category, price, stock, status) VALUES
('SKU001', 'iPhone 16 Pro', '数码电子', 8999.00, 50, 'active'),
('SKU002', 'MacBook Air M4', '数码电子', 10499.00, 30, 'active'),
('SKU003', 'Nike Air Max', '运动鞋服', 899.00, 100, 'active'),
('SKU004', '戴森吸尘器 V15', '生活家电', 4990.00, 20, 'active');

-- 插入客户示例数据
INSERT INTO customers (customer_name, phone, email, level) VALUES
('张三', '13800000001', 'zhangsan@example.com', 'vip'),
('李四', '13800000002', 'lisi@example.com', 'vip'),
('王五', '13800000003', 'wangwu@example.com', 'normal'),
('赵六', '13800000004', 'zhaoliu@example.com', 'normal');

-- 插入一些示例数据
INSERT INTO orders (order_no, product_name, category, price, quantity, total_amount, customer_name, status, created_at) VALUES
('ORD2026001', 'iPhone 16 Pro', '数码电子', 8999.00, 1, 8999.00, '张三', 'completed', '2026-01-15 10:30:00'),
('ORD2026002', 'MacBook Air M4', '数码电子', 10499.00, 1, 10499.00, '李四', 'completed', '2026-02-20 14:20:00'),
('ORD2026003', 'AirPods Pro 3', '数码电子', 1799.00, 2, 3598.00, '王五', 'completed', '2026-03-10 09:15:00'),
('ORD2026004', 'Nike Air Max', '运动鞋服', 899.00, 2, 1798.00, '赵六', 'completed', '2026-04-05 16:45:00'),
('ORD2026005', 'Adidas Ultraboost', '运动鞋服', 1299.00, 1, 1299.00, '张三', 'completed', '2026-05-12 11:00:00'),
('ORD2026006', '戴森吸尘器 V15', '生活家电', 4990.00, 1, 4990.00, '李四', 'completed', '2026-06-18 13:30:00'),
('ORD2026007', 'SK-II 神仙水', '美妆护肤', 1590.00, 1, 1590.00, '王五', 'completed', '2026-06-25 10:00:00'),
('ORD2026008', 'iPad Pro M4', '数码电子', 6799.00, 1, 6799.00, '赵六', 'completed', '2026-07-01 15:00:00');
