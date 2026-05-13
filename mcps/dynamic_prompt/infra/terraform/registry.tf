resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "dynamic-prompt"
  format        = "DOCKER"
  description   = "dynamic-prompt MCP server"

  depends_on = [google_project_service.apis]
}
