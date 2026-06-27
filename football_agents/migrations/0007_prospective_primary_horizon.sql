ALTER TABLE prospective_research_studies
ADD COLUMN primary_horizon_minutes INTEGER NOT NULL DEFAULT 60;

ALTER TABLE prospective_research_studies
ADD COLUMN horizon_tolerance_minutes INTEGER NOT NULL DEFAULT 60;
