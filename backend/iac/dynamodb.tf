# All 7 tables, mirroring backend/scripts/create_tables.py exactly (which is
# the source of truth the application code is written against). Every key
# attribute is a string — model `version` is free-form ("1", "2.1.0") and the
# old cross-tenant name-index was deliberately removed.

locals {
  tables = {
    tenants = {
      hash_key  = "tenant_id"
      range_key = null
      gsis = {
        "status-index" = { hash = "status", range = "tenant_id" }
      }
    }
    group-mappings = {
      hash_key  = "group_id"
      range_key = null
      gsis      = {}
    }
    pipelines = {
      hash_key  = "tenant_id"
      range_key = "pipeline_id"
      gsis = {
        "status-index" = { hash = "status", range = "updatedAt" }
        "all-index"    = { hash = "all_pk", range = "all_sk" }
      }
    }
    jobs = {
      hash_key  = "tenant_id"
      range_key = "job_id"
      gsis = {
        "run-id-index" = { hash = "run_id", range = "tenant_id" }
        "status-index" = { hash = "status", range = "submittedAt" }
        "all-index"    = { hash = "all_pk", range = "all_sk" }
      }
    }
    models = {
      hash_key  = "tenant_id"
      range_key = "sk"
      gsis = {
        "stage-index" = { hash = "stage", range = "stage_sk" }
        "all-index"   = { hash = "all_pk", range = "all_sk" }
      }
    }
    monitoring-snapshots = {
      hash_key  = "tenant_id"
      range_key = "sk"
      gsis = {
        "model-trend-index" = { hash = "model_trend_pk", range = "recordedAt" }
        "status-index"      = { hash = "derivedStatus", range = "recordedAt" }
        "all-index"         = { hash = "all_pk", range = "recordedAt" }
      }
    }
    audit = {
      hash_key  = "tenant_id"
      range_key = "sk"
      gsis = {
        "all-index"    = { hash = "event_date", range = "sk" }
        "actor-index"  = { hash = "actor", range = "sk" }
        "entity-index" = { hash = "entity_pk", range = "sk" }
      }
    }
  }

  # Every attribute referenced as a key (table or GSI), per table. All string.
  table_attributes = {
    for name, t in local.tables : name => distinct(compact(concat(
      [t.hash_key, t.range_key],
      flatten([for _, g in t.gsis : [g.hash, g.range]]),
    )))
  }
}

resource "aws_dynamodb_table" "this" {
  for_each = local.tables

  name         = "${var.name_prefix}-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = each.value.hash_key
  range_key    = each.value.range_key

  deletion_protection_enabled = var.enable_deletion_protection

  dynamic "attribute" {
    for_each = local.table_attributes[each.key]
    content {
      name = attribute.value
      type = "S"
    }
  }

  dynamic "global_secondary_index" {
    for_each = each.value.gsis
    content {
      name            = global_secondary_index.key
      hash_key        = global_secondary_index.value.hash
      range_key       = global_secondary_index.value.range
      projection_type = "ALL"
    }
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled = true # AWS-owned key; switch to a CMK via kms_key_arn if mandated
  }

  tags = var.tags
}
