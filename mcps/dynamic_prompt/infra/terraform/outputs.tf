output "service_url" {
  description = "Cloud Run service URL"
  value       = google_cloud_run_v2_service.app.uri
}

output "mcp_endpoint" {
  description = "MCP client connection endpoint"
  value       = "${google_cloud_run_v2_service.app.uri}/mcp"
}

output "image_repo" {
  description = "Artifact Registry image path (tag なし)"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/dynamic-prompt/server"
}
