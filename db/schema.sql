-- =============================================================================
-- 智选志愿 · 数据库 Schema v1（河南试点）
-- 目标库：PostgreSQL 16 + pgvector
-- 作者：张（数据工程 + 数据库设计）
-- 生成日期：2026-10-11
--
-- 铁律（写进约束）：
--   1. 所有**事实表**必须能追溯到来源：source_id NOT NULL + 外键
--   2. 所有**事实表**必须带 year（NOT NULL）
--   3. 枚举字段用 CHECK 约束，禁止魔法值
--   4. 用户密码只存 hash，禁止明文
--
-- 使用：
--   createdb zhixuan
--   psql -U postgres -d zhixuan -f db/schema.sql
-- =============================================================================

-- pgvector 为可选扩展：装了则启用向量检索；未装则跳过（RAG 向量列缺省），
-- 其余表结构与约束不受影响，保证 schema 在任意 PostgreSQL 上都可执行。
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
    RAISE NOTICE 'pgvector 已启用';
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector 未安装，跳过（knowledge_chunk.embedding 将不作为列创建）';
END $$;

-- =============================================================================
-- 0. 来源登记表 —— 一切事实数据的锚点
-- =============================================================================
CREATE TABLE IF NOT EXISTS source (
    id          BIGSERIAL   PRIMARY KEY,
    source_name TEXT        NOT NULL,                       -- 河南省教育考试院 / 阳光高考 ...
    source_url  TEXT        NOT NULL,
    year        SMALLINT    NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    source_type TEXT        NOT NULL DEFAULT '官方'
                            CHECK (source_type IN ('官方','公开网络','投稿')),
    reliability TEXT        NOT NULL DEFAULT 'high'
                            CHECK (reliability IN ('high','medium','low')),
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_name, source_url, year)
);
COMMENT ON TABLE source IS '来源登记：事实数据先登记来源，再以 source_id 引用入库';

-- =============================================================================
-- 通用触发器：自动维护 updated_at
-- =============================================================================
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 1. 升学途径（河南三大专项是 P0 核心）
-- =============================================================================
CREATE TABLE IF NOT EXISTS pathway (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT      NOT NULL UNIQUE,                  -- 国家专项计划 / 地方专项计划 ...
    category    TEXT,                                       -- 拔尖类/专项类/定向类/军警类/艺体类/其他
    batch       TEXT,                                       -- 所属批次
    target_group TEXT,                                      -- 面向人群
    apply_time  TEXT,                                       -- 关键时间节点（原样文本）
    description TEXT,
    priority    TEXT      NOT NULL DEFAULT 'P0'
                          CHECK (priority IN ('P0','P1','P2')),
    data_status TEXT      NOT NULL DEFAULT 'available'
                          CHECK (data_status IN ('available','schema_only')),  -- P2 标"规划中"
    source_id   BIGINT    NOT NULL REFERENCES source(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pathway_eligibility (             -- 资格规则（喂给规则引擎）
    id          BIGSERIAL PRIMARY KEY,
    pathway_id  BIGINT    NOT NULL REFERENCES pathway(id),
    province    TEXT      NOT NULL DEFAULT '河南',
    rule_type   TEXT      NOT NULL CHECK (rule_type IN ('户籍','学籍','区域','成绩','其他')),
    rule_desc   TEXT      NOT NULL,                         -- 人类可读规则条文
    params      JSONB,                                      -- 结构化参数，如 {"household":"农村"}
    source_id   BIGINT    NOT NULL REFERENCES source(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (pathway_id, province, rule_type, rule_desc)     -- 保证可幂等重载
);
CREATE INDEX IF NOT EXISTS idx_pathway_eligibility_lookup
    ON pathway_eligibility(pathway_id, province, rule_type);

CREATE TABLE IF NOT EXISTS pathway_region (                 -- 专项实施区域县名单
    id          BIGSERIAL PRIMARY KEY,
    pathway_id  BIGINT    NOT NULL REFERENCES pathway(id),
    province    TEXT      NOT NULL DEFAULT '河南',
    county_name TEXT      NOT NULL,                         -- 兰考县 / 嵩县 ...
    county_code TEXT,                                       -- 行政区划码（精确匹配优先）
    source_id   BIGINT    NOT NULL REFERENCES source(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (pathway_id, province, county_code)
);
CREATE INDEX IF NOT EXISTS idx_pathway_region_county
    ON pathway_region(province, county_name);

-- =============================================================================
-- 2. 基础院校 / 专业库
-- =============================================================================
CREATE TABLE IF NOT EXISTS school (
    id        BIGSERIAL PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,                         -- 院校全称
    code      TEXT,                                         -- 全国通用代码（如 10459）
    province  TEXT,
    city      TEXT,
    level     TEXT,                                         -- 本科/专科
    type      TEXT,                                         -- 综合/理工/师范/医药...
    ownership TEXT,                                         -- 公办/民办
    website   TEXT,
    intro     TEXT,
    is_211    BOOLEAN,
    is_985    BOOLEAN,
    dual_class TEXT,                                        -- 双一流类别
    external_id TEXT,                                       -- 外部站点 ID（如掌上高考 school_id）
    source_id BIGINT NOT NULL REFERENCES source(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_school_province ON school(province);
CREATE INDEX IF NOT EXISTS idx_school_level    ON school(level);
CREATE INDEX IF NOT EXISTS idx_school_name     ON school(name);

CREATE TABLE IF NOT EXISTS major (
    id        BIGSERIAL PRIMARY KEY,
    name      TEXT NOT NULL,
    code      TEXT,                                         -- 专业代码
    category  TEXT,                                         -- 门类/专业类
    degree    TEXT,                                         -- 授予学位
    intro     TEXT,
    source_id BIGINT NOT NULL REFERENCES source(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (code)
);
CREATE INDEX IF NOT EXISTS idx_major_category ON major(category);
CREATE INDEX IF NOT EXISTS idx_major_name     ON major(name);

-- =============================================================================
-- 3. 录取分数（核心事实表）
--    注意：河南 2025 起首年新高考，2023-2024 为老高考（文/理），
--         2025+ 为历史类/物理类，且普通本科批按【院校专业组】投档 → group_code
-- =============================================================================
CREATE TABLE IF NOT EXISTS school_major_score (
    id           BIGSERIAL PRIMARY KEY,
    school_id    BIGINT   NOT NULL REFERENCES school(id),
    major_id     BIGINT   REFERENCES major(id),             -- 院校专业组投档时可为空
    province     TEXT     NOT NULL DEFAULT '河南',
    year         SMALLINT NOT NULL,
    batch        TEXT     NOT NULL,                         -- 本科提前批/本科批/高职高专批...
    subject_type TEXT     NOT NULL
                 CHECK (subject_type IN ('文科','理科','历史类','物理类','综合')),
    group_code   TEXT,                                      -- 院校专业组代码（新高考 2025+）
    group_name   TEXT,
    min_score    NUMERIC(6,1),                              -- 最低分（含同分排序时可能带小数）
    min_rank     INTEGER,                                   -- 最低位次
    avg_score    NUMERIC(6,1),
    plan_count   INTEGER,                                   -- 招生计划数
    pathway_id   BIGINT   REFERENCES pathway(id),            -- 专项计划录取时关联
    source_id    BIGINT   NOT NULL REFERENCES source(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT
        (school_id, major_id, province, year, batch, subject_type, group_code)
);
CREATE INDEX IF NOT EXISTS idx_sms_core   ON school_major_score(province, year, batch, subject_type);
CREATE INDEX IF NOT EXISTS idx_sms_school ON school_major_score(school_id, year);
CREATE INDEX IF NOT EXISTS idx_sms_rank   ON school_major_score(province, year, subject_type, min_rank);
CREATE INDEX IF NOT EXISTS idx_sms_path   ON school_major_score(pathway_id);

CREATE TABLE IF NOT EXISTS pathway_score (                   -- 专项/特殊路径录取参考（D-4）
    id           BIGSERIAL PRIMARY KEY,
    pathway_id   BIGINT   NOT NULL REFERENCES pathway(id),   -- 国家专项计划 / 地方专项计划 / 高校专项计划
    school_id    BIGINT   NOT NULL REFERENCES school(id),
    major_id     BIGINT   REFERENCES major(id),
    province     TEXT     NOT NULL DEFAULT '河南',
    year         SMALLINT NOT NULL,
    batch        TEXT,                                       -- 2025 起专项并入普通本科批
    subject_type TEXT
                 CHECK (subject_type IS NULL OR
                        subject_type IN ('文科','理科','历史类','物理类','综合')),
    group_code   TEXT,                                       -- 院校专业组代码（如 301），2025 新高考关键
    group_name   TEXT,                                       -- 如「本科批：第301组(国家专项计划)」
    min_score    NUMERIC(6,1) CHECK (min_score IS NULL OR min_score BETWEEN 0 AND 750),
    max_score    NUMERIC(6,1) CHECK (max_score IS NULL OR max_score BETWEEN 0 AND 750),
    min_rank     INTEGER,
    admitted_num INTEGER,                                    -- 录取人数（如来源公布）
    source_id    BIGINT   NOT NULL REFERENCES source(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- group_code 可空（部分来源不公布组号），NULLS NOT DISTINCT 保证 upsert 幂等
    UNIQUE NULLS NOT DISTINCT
        (pathway_id, school_id, province, year, subject_type, group_code)
);
CREATE INDEX IF NOT EXISTS idx_pathway_score_lookup
    ON pathway_score(pathway_id, province, year);
CREATE INDEX IF NOT EXISTS idx_pathway_score_school
    ON pathway_score(school_id, year);

-- 一分一段表（分数 <-> 位次，方案计算的基准）
CREATE TABLE IF NOT EXISTS score_segment (
    id                BIGSERIAL PRIMARY KEY,
    province          TEXT     NOT NULL DEFAULT '河南',
    year              SMALLINT NOT NULL,
    subject_type      TEXT     NOT NULL
                      CHECK (subject_type IN ('文科','理科','历史类','物理类','综合')),
    score             INTEGER  NOT NULL CHECK (score BETWEEN 0 AND 750),
    score_end         INTEGER,                              -- 区间上界（仅最高分段，如 710-750）
    same_score_count  INTEGER,                              -- 本段人数
    cumulative_rank   INTEGER  NOT NULL,                    -- 累计人数（该分及以上）
    source_id         BIGINT   NOT NULL REFERENCES source(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (province, year, subject_type, score)
);
CREATE INDEX IF NOT EXISTS idx_seg_score ON score_segment(province, year, subject_type, score);
CREATE INDEX IF NOT EXISTS idx_seg_rank  ON score_segment(province, year, subject_type, cumulative_rank);

-- 批次录取控制分数线（省控线）：冲稳保与资格判定都要用
CREATE TABLE IF NOT EXISTS batch_score_line (
    id           BIGSERIAL PRIMARY KEY,
    province     TEXT     NOT NULL DEFAULT '河南',
    year         SMALLINT NOT NULL,
    batch        TEXT     NOT NULL,                         -- 特殊类型/普通本科批/本科一批/高职高专批...
    subject_type TEXT     NOT NULL
                 CHECK (subject_type IN ('文科','理科','历史类','物理类','综合')),
    score        INTEGER  NOT NULL CHECK (score BETWEEN 0 AND 750),
    source_id    BIGINT   NOT NULL REFERENCES source(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (province, year, batch, subject_type)
);
CREATE INDEX IF NOT EXISTS idx_line_lookup
    ON batch_score_line(province, year, batch, subject_type);

-- 招生章程 / 录取规则
CREATE TABLE IF NOT EXISTS enrollment_rule (
    id             BIGSERIAL PRIMARY KEY,
    school_id      BIGINT   NOT NULL REFERENCES school(id),
    year           SMALLINT NOT NULL,
    content        TEXT,
    subject_req    TEXT,                                    -- 选科要求
    health_req     TEXT,                                    -- 体检要求
    foreign_lang_req TEXT,                                  -- 外语语种要求
    source_id      BIGINT   NOT NULL REFERENCES source(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (school_id, year)                                -- 一校一年一份章程，可幂等重载
);
CREATE INDEX IF NOT EXISTS idx_enrollment_rule ON enrollment_rule(school_id, year);

-- 学科评估
CREATE TABLE IF NOT EXISTS discipline_eval (
    id             BIGSERIAL PRIMARY KEY,
    school_id      BIGINT NOT NULL REFERENCES school(id),
    discipline_name TEXT  NOT NULL,
    grade          TEXT,                                    -- A+/A/B+...
    round          TEXT,                                    -- 第四轮/第五轮
    source_id      BIGINT NOT NULL REFERENCES source(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 同一学校同一轮次同一学科只有一条结果（幂等 upsert 依据）
    UNIQUE (school_id, discipline_name, round)
);
CREATE INDEX IF NOT EXISTS idx_discipline_school ON discipline_eval(school_id);

-- 兼容既有库：补 (school_id, discipline_name, round) 唯一键（幂等 upsert 依据）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'discipline_eval'::regclass
          AND conname  = 'discipline_eval_school_id_discipline_name_round_key'
    ) THEN
        ALTER TABLE discipline_eval
            ADD CONSTRAINT discipline_eval_school_id_discipline_name_round_key
            UNIQUE (school_id, discipline_name, round);
    END IF;
END $$;

-- =============================================================================
-- 4. 院校画像与生活信息
-- =============================================================================
CREATE TABLE IF NOT EXISTS school_profile (
    id                     BIGSERIAL PRIMARY KEY,
    school_id              BIGINT NOT NULL REFERENCES school(id) UNIQUE,
    tuition_range          TEXT,
    accommodation_fee      TEXT,
    campus_list            JSONB,                           -- [{name,address,city}]
    established_year       INTEGER,
    master_phd_points      JSONB,                           -- {master,phd}
    first_class_major_count INTEGER,                        -- 国家级一流本科专业数
    faculty_count          INTEGER,
    student_faculty_ratio  TEXT,
    source_note            TEXT NOT NULL,                   -- 来源说明（必填）
    source_id              BIGINT NOT NULL REFERENCES source(id),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS school_life (
    id          BIGSERIAL PRIMARY KEY,
    school_id   BIGINT NOT NULL REFERENCES school(id),
    category    TEXT,                                       -- 宿舍/食堂/交通...
    content     TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT '公开网络'
                CHECK (source_type IN ('官方','公开网络','投稿')),
    source_name TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    year        SMALLINT NOT NULL,
    reliability TEXT NOT NULL DEFAULT 'medium'
                CHECK (reliability IN ('high','medium','low')),
    source_id   BIGINT NOT NULL REFERENCES source(id),      -- 来源铁律：事实表必带 source_id
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 同一院校同一类别同一正文只保留一条（幂等 upsert 依据）
    UNIQUE (school_id, category, content)
);
CREATE INDEX IF NOT EXISTS idx_life_school ON school_life(school_id, category);

-- 兼容既有库：补 (school_id, category, content) 唯一键（幂等 upsert 依据）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'school_life'::regclass
          AND conname  = 'school_life_school_id_category_content_key'
    ) THEN
        ALTER TABLE school_life
            ADD CONSTRAINT school_life_school_id_category_content_key
            UNIQUE (school_id, category, content);
    END IF;
    -- 兼容既有库：补 source_id 列（来源铁律）
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'school_life' AND column_name = 'source_id'
    ) THEN
        ALTER TABLE school_life ADD COLUMN source_id BIGINT REFERENCES source(id);
    END IF;
END $$;

-- =============================================================================
-- 5. 知识库（RAG）
-- =============================================================================
CREATE TABLE IF NOT EXISTS knowledge_doc (
    id          BIGSERIAL PRIMARY KEY,
    title       TEXT     NOT NULL,
    source_name TEXT     NOT NULL,
    source_url  TEXT     NOT NULL,
    year        SMALLINT NOT NULL,
    doc_type    TEXT,                                       -- 政策/章程/名单/问答...
    province    TEXT     DEFAULT '河南',
    pathway_id  BIGINT   REFERENCES pathway(id),
    content     TEXT,
    source_id   BIGINT   NOT NULL REFERENCES source(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (title, source_url)                              -- 同标题+同来源视为一篇，可幂等重载
);
CREATE INDEX IF NOT EXISTS idx_doc_filter ON knowledge_doc(province, year, pathway_id);

CREATE TABLE IF NOT EXISTS knowledge_chunk (
    id          BIGSERIAL PRIMARY KEY,
    doc_id      BIGINT   NOT NULL REFERENCES knowledge_doc(id) ON DELETE CASCADE,
    content     TEXT     NOT NULL,
    chunk_index INTEGER  NOT NULL,
    meta        JSONB,
    province    TEXT     DEFAULT '河南',
    pathway_id  BIGINT   REFERENCES pathway(id),
    source_id   BIGINT   NOT NULL REFERENCES source(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- embedding 列与 HNSW 索引仅在 pgvector 可用时创建（见文件顶部说明）
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        ALTER TABLE knowledge_chunk ADD COLUMN IF NOT EXISTS embedding vector(512);
        -- HNSW 向量索引（余弦距离）
        CREATE INDEX IF NOT EXISTS idx_chunk_embedding
            ON knowledge_chunk USING hnsw (embedding vector_cosine_ops);
        RAISE NOTICE 'knowledge_chunk.embedding 列与 HNSW 索引已创建';
    ELSE
        RAISE NOTICE 'pgvector 不可用：跳过 knowledge_chunk.embedding 与 HNSW 索引';
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_chunk_filter
    ON knowledge_chunk(province, pathway_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_chunk_doc_idx
    ON knowledge_chunk(doc_id, chunk_index);

-- =============================================================================
-- 6. 用户系统
-- =============================================================================
CREATE TABLE IF NOT EXISTS app_user (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT,
    phone         TEXT,
    password_hash TEXT NOT NULL,                            -- 只存 bcrypt hash
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled','deleted')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS user_profile (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            BIGINT NOT NULL UNIQUE REFERENCES app_user(id) ON DELETE CASCADE,
    province           TEXT   NOT NULL DEFAULT '河南',
    exam_type          TEXT   NOT NULL DEFAULT '普通' CHECK (exam_type IN ('普通','艺术','体育')),
    first_subject      TEXT   CHECK (first_subject IN ('物理','历史')),
    second_subjects    JSONB,                               -- ["化学","地理"]
    score              INTEGER CHECK (score BETWEEN 0 AND 750),
    rank               INTEGER CHECK (rank > 0),
    -- ---- 契约 docs/api-contract.md §2 字段（追加字段，可缺省）----
    household_type     TEXT   CHECK (household_type IN ('城镇','农村')),
    household_county   TEXT,                                -- 户籍所在县（区）
    enrollment_county  TEXT,                                -- 学籍所在县（区）
    household_years    INTEGER CHECK (household_years >= 0),
    enrollment_years   INTEGER CHECK (enrollment_years >= 0),
    parent_household_local BOOLEAN,                         -- 法定监护人户籍是否在当地
    special_marks      JSONB,                               -- ["少数民族","烈士子女"]
    preferences        JSONB,                               -- {priority, preferred_majors, preferred_cities, accept_adjustment}
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_favorite (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    target_type TEXT   NOT NULL CHECK (target_type IN ('school','major','school_major')),
    target_id   BIGINT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS user_plan (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    name       TEXT   NOT NULL,
    strategy   TEXT   NOT NULL CHECK (strategy IN ('冲','稳','保')),   -- 契约 §5：档位策略
    priority   TEXT   CHECK (priority IN ('城市优先','专业优先','院校优先')), -- 契约 §5：偏好倾向
    items      JSONB  NOT NULL,                             -- PlanItem[]
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_plan_user ON user_plan(user_id);

-- =============================================================================
-- 7. 问答日志与人工审核闭环
-- =============================================================================
CREATE TABLE IF NOT EXISTS qa_log (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT REFERENCES app_user(id),
    session_id   TEXT,
    question     TEXT NOT NULL,
    answer       TEXT,
    citations    JSONB,
    confidence   TEXT CHECK (confidence IN ('high','medium','low')),
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    degraded     BOOLEAN NOT NULL DEFAULT FALSE,
    status       TEXT NOT NULL DEFAULT 'open',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qa_session ON qa_log(session_id);

CREATE TABLE IF NOT EXISTS review_task (
    id               BIGSERIAL PRIMARY KEY,
    qa_log_id        BIGINT NOT NULL REFERENCES qa_log(id),
    status           TEXT   NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','corrected','rejected')),
    trigger_reason   TEXT,
    reviewer         TEXT,
    comment          TEXT,
    corrected_answer TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_task(status);

-- 管理端账号与操作留痕
CREATE TABLE IF NOT EXISTS admin_user (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'admin',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id         BIGSERIAL PRIMARY KEY,
    admin_id   BIGINT NOT NULL,
    action     TEXT   NOT NULL,                             -- 导入语料 / 重建索引 / 审核...
    target     TEXT,
    detail     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =============================================================================
-- 8. 采集暂存区（staging）—— 原始数据先落这里，清洗校验后再入正式表
--    这样"来源三要素不全"的行会被挡在正式表之外
-- =============================================================================
CREATE TABLE IF NOT EXISTS stg_import (
    id           BIGSERIAL PRIMARY KEY,
    batch_no     TEXT   NOT NULL,                           -- 采集批次号，如 20261011_haeea_segment
    source_name  TEXT   NOT NULL,
    source_url   TEXT   NOT NULL,
    year         SMALLINT,
    doc_type     TEXT,                                      -- score_segment / admission / school ...
    raw          JSONB  NOT NULL,                           -- 一行原始记录
    row_no       INTEGER,
    status       TEXT   NOT NULL DEFAULT 'new'
                 CHECK (status IN ('new','validated','loaded','rejected')),
    reject_reason TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_stg_batch ON stg_import(batch_no, status);

-- =============================================================================
-- 9. 更新 updated_at 触发器
-- =============================================================================
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'pathway','school','major','school_major_score',
        'enrollment_rule','school_profile','user_plan','user_profile'
    ] LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_%1$s_updated ON %1$s;
             CREATE TRIGGER trg_%1$s_updated BEFORE UPDATE ON %1$s
             FOR EACH ROW EXECUTE FUNCTION set_updated_at();', t);
    END LOOP;
END $$;

-- =============================================================================
-- 10. 兼容迁移：user_profile / user_plan 对齐 api-contract.md
--     旧库可能已用旧列名建表（IF NOT EXISTS 不会改列），此处补齐/改名
-- =============================================================================
DO $$
BEGIN
    -- user_profile：旧列 -> 契约列
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='user_profile' AND column_name='home_county')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='user_profile' AND column_name='household_county') THEN
        ALTER TABLE user_profile RENAME COLUMN home_county TO household_county;
    END IF;

    -- 契约新增列（可缺省）
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='user_profile' AND column_name='household_county') THEN
        ALTER TABLE user_profile ADD COLUMN household_county TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='user_profile' AND column_name='enrollment_county') THEN
        ALTER TABLE user_profile ADD COLUMN enrollment_county TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='user_profile' AND column_name='household_years') THEN
        ALTER TABLE user_profile ADD COLUMN household_years INTEGER;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='user_profile' AND column_name='enrollment_years') THEN
        ALTER TABLE user_profile ADD COLUMN enrollment_years INTEGER;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='user_profile' AND column_name='parent_household_local') THEN
        ALTER TABLE user_profile ADD COLUMN parent_household_local BOOLEAN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='user_profile' AND column_name='special_marks') THEN
        ALTER TABLE user_profile ADD COLUMN special_marks JSONB;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='user_profile' AND column_name='preferences') THEN
        ALTER TABLE user_profile ADD COLUMN preferences JSONB;
    END IF;

    -- user_plan：strategy 语义由 school/major/city 改为 冲/稳/保，并新增 priority
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='user_plan' AND column_name='priority') THEN
        ALTER TABLE user_plan ADD COLUMN priority TEXT;
    END IF;

    -- user_profile：把旧列 preferred_cities/preferred_majors 的值并入 preferences，再删除冗余旧列
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='user_profile' AND column_name='preferred_cities') THEN
        UPDATE user_profile SET preferences = jsonb_strip_nulls(jsonb_build_object(
            'preferred_cities', preferred_cities,
            'preferred_majors', preferred_majors))
        WHERE preferences IS NULL AND (preferred_cities IS NOT NULL OR preferred_majors IS NOT NULL);
        ALTER TABLE user_profile DROP COLUMN IF EXISTS preferred_cities;
        ALTER TABLE user_profile DROP COLUMN IF EXISTS preferred_majors;
    END IF;
    -- 其余旧冗余列（契约中无对应字段，统一移除）
    ALTER TABLE user_profile DROP COLUMN IF EXISTS home_county_code;
    ALTER TABLE user_profile DROP COLUMN IF EXISTS school_years;
    ALTER TABLE user_profile DROP COLUMN IF EXISTS has_national_special;
    ALTER TABLE user_profile DROP COLUMN IF EXISTS has_local_special;
    ALTER TABLE user_profile DROP COLUMN IF EXISTS has_college_special;
    ALTER TABLE user_profile DROP COLUMN IF EXISTS tuition_budget;
END $$;

-- 重建 user_plan.strategy 的 CHECK 约束（旧约束若存在则替换为档位语义）
DO $$
DECLARE cname TEXT;
BEGIN
    -- 先删除 user_plan 上所有涉及 strategy / priority 的旧 CHECK 约束（幂等）
    FOR cname IN
        SELECT conname FROM pg_constraint
        WHERE conrelid='user_plan'::regclass AND contype='c'
          AND (pg_get_constraintdef(oid) ILIKE '%strategy%'
               OR pg_get_constraintdef(oid) ILIKE '%priority%')
    LOOP
        EXECUTE format('ALTER TABLE user_plan DROP CONSTRAINT %I', cname);
    END LOOP;
    ALTER TABLE user_plan
        ADD CONSTRAINT user_plan_strategy_check CHECK (strategy IN ('冲','稳','保'));
    ALTER TABLE user_plan
        ADD CONSTRAINT user_plan_priority_check
        CHECK (priority IS NULL OR priority IN ('城市优先','专业优先','院校优先'));
END $$;
