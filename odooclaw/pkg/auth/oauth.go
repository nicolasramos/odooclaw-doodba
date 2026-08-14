package auth

import (
	"bufio"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"
)

type OAuthProviderConfig struct {
	Issuer       string
	ClientID     string
	ClientSecret string // Required for Google OAuth (confidential client)
	TokenURL     string // Override token endpoint (Google uses a different URL than issuer)
	Scopes       string
	Originator   string
	Port         int
}

func OpenAIOAuthConfig() OAuthProviderConfig {
	return OAuthProviderConfig{
		Issuer:     "https://auth.openai.com",
		ClientID:   "app_EMoamEEZ73f0CkXaXp7hrann",
		Scopes:     "openid profile email offline_access",
		Originator: "codex_cli_rs",
		Port:       1455,
	}
}

// GoogleAntigravityOAuthConfig returns the OAuth configuration for Google Cloud Code Assist (Antigravity).
// Client credentials must be provided by deployment configuration.
func GoogleAntigravityOAuthConfig() OAuthProviderConfig {
	clientID := os.Getenv("ODOOCLAW_GOOGLE_OAUTH_CLIENT_ID")
	clientSecret := os.Getenv("ODOOCLAW_GOOGLE_OAUTH_CLIENT_SECRET")
	return OAuthProviderConfig{
		Issuer:       "https://accounts.google.com/o/oauth2/v2",
		TokenURL:     "https://oauth2.googleapis.com/token",
		ClientID:     clientID,
		ClientSecret: clientSecret,
		Scopes:       "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/cclog https://www.googleapis.com/auth/experimentsandconfigs",
		Port:         51121,
	}
}
