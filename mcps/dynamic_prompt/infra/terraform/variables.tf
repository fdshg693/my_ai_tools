variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "asia-northeast1"
}

variable "image_tag" {
  description = "Container image tag (Cloud Build で事前にビルド)"
  type        = string
  default     = "latest"
}

variable "google_client_id" {
  description = "Google OAuth Client ID"
  type        = string
}

variable "google_client_secret" {
  description = "Google OAuth Client Secret"
  type        = string
  sensitive   = true
}

variable "service_url" {
  description = "Cloud Run service URL (OAuth base_url に使用)"
  type        = string
}

variable "allowed_emails" {
  description = "MCP 接続を許可する Google アカウントのメールアドレス（カンマ区切り）。空文字なら全 Google アカウント許可"
  type        = string
  default     = ""
}
