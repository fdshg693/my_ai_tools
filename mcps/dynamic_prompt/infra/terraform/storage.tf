resource "google_storage_bucket" "data" {
  name     = "${var.project_id}-dp-data"
  location = var.region

  uniform_bucket_level_access = true

  lifecycle {
    prevent_destroy = true
  }
}
