locals {
  image = "${var.region}-docker.pkg.dev/${var.project_id}/dynamic-prompt/server:${var.image_tag}"
}

resource "google_cloud_run_v2_service" "app" {
  name     = "dynamic-prompt"
  location = var.region

  launch_stage = "GA"

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 1 # SQLite 使用時は単一インスタンスに制限
    }

    volumes {
      name = "dp-data"
      gcs {
        bucket    = google_storage_bucket.data.name
        read_only = false
      }
    }

    containers {
      image = local.image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          memory = "512Mi"
          cpu    = "1"
        }
      }

      env {
        name  = "TRANSPORT"
        value = "http"
      }
      env {
        name  = "DB_PATH"
        value = "/data/vocab.db"
      }
      env {
        name  = "GOOGLE_CLIENT_ID"
        value = var.google_client_id
      }
      env {
        name  = "GOOGLE_CLIENT_SECRET"
        value = var.google_client_secret
      }
      env {
        name  = "SERVICE_URL"
        value = var.service_url
      }
      env {
        name  = "ALLOWED_EMAILS"
        value = var.allowed_emails
      }
      env {
        name  = "FASTMCP_HOME"
        value = "/data/.fastmcp"
      }
      env {
        name  = "PROMPTS_URI"
        value = "gs://${google_storage_bucket.data.name}/prompts"
      }
      env {
        name  = "CONFIG_TTL_SECONDS"
        value = "60"
      }

      volume_mounts {
        name       = "dp-data"
        mount_path = "/data"
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_artifact_registry_repository.repo,
  ]
}
