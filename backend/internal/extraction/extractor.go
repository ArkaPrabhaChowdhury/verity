package extraction

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
	"unicode"

	"golang.org/x/net/html"
)

const maxHTMLBytes = 4 << 20

type Document struct {
	URL   string
	Title string
	Text  string
}

type Extractor struct {
	client  *http.Client
	maxText int
}

func New(timeout time.Duration, maxText int) *Extractor {
	if maxText <= 0 {
		maxText = 1_800
	}
	dialer := &net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}
	transport := &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			host, port, err := net.SplitHostPort(address)
			if err != nil {
				return nil, err
			}
			ips, err := net.DefaultResolver.LookupIPAddr(ctx, host)
			if err != nil {
				return nil, err
			}
			for _, ip := range ips {
				if unsafeIP(ip.IP) {
					return nil, fmt.Errorf("refusing non-public address for %s", host)
				}
			}
			if len(ips) == 0 {
				return nil, fmt.Errorf("no address found for %s", host)
			}
			return dialer.DialContext(ctx, network, net.JoinHostPort(ips[0].IP.String(), port))
		},
		TLSHandshakeTimeout: 5 * time.Second,
	}
	client := &http.Client{Timeout: timeout, Transport: transport}
	client.CheckRedirect = func(req *http.Request, via []*http.Request) error {
		if len(via) >= 5 {
			return errors.New("too many redirects")
		}
		return validateURL(req.URL)
	}
	return &Extractor{client: client, maxText: maxText}
}

func (e *Extractor) Fetch(ctx context.Context, rawURL string) (Document, error) {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return Document{}, err
	}
	if err := validateURL(parsed); err != nil {
		return Document{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, parsed.String(), nil)
	if err != nil {
		return Document{}, err
	}
	req.Header.Set("User-Agent", "VerityResearchBot/1.0 (+https://github.com/arkop/verity)")
	req.Header.Set("Accept", "text/html,application/xhtml+xml")
	resp, err := e.client.Do(req)
	if err != nil {
		return Document{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return Document{}, &HTTPError{StatusCode: resp.StatusCode}
	}
	contentType := resp.Header.Get("Content-Type")
	if contentType != "" && !strings.Contains(contentType, "text/html") && !strings.Contains(contentType, "application/xhtml") {
		return Document{}, fmt.Errorf("unsupported content type %q", contentType)
	}
	root, err := html.Parse(io.LimitReader(resp.Body, maxHTMLBytes))
	if err != nil {
		return Document{}, fmt.Errorf("parse HTML: %w", err)
	}
	title := titleText(root)
	text := extractText(root)
	if len(text) < 160 {
		return Document{}, fmt.Errorf("insufficient extractable content")
	}
	if len(text) > e.maxText {
		text = truncateRunes(text, e.maxText)
	}
	return Document{URL: resp.Request.URL.String(), Title: title, Text: text}, nil
}

func truncateRunes(value string, limit int) string {
	runes := []rune(value)
	if len(runes) <= limit {
		return value
	}
	return string(runes[:limit])
}

func validateURL(u *url.URL) error {
	if u.Scheme != "http" && u.Scheme != "https" {
		return fmt.Errorf("unsupported URL scheme")
	}
	if u.User != nil || u.Hostname() == "" {
		return fmt.Errorf("invalid public URL")
	}
	host := strings.ToLower(u.Hostname())
	if host == "localhost" || strings.HasSuffix(host, ".localhost") || strings.HasSuffix(host, ".local") {
		return fmt.Errorf("refusing local URL")
	}
	if ip := net.ParseIP(host); ip != nil && unsafeIP(ip) {
		return fmt.Errorf("refusing non-public address")
	}
	return nil
}

func unsafeIP(ip net.IP) bool {
	return ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() || ip.IsUnspecified() || ip.IsMulticast()
}

func titleText(root *html.Node) string {
	var walk func(*html.Node) string
	walk = func(n *html.Node) string {
		if n.Type == html.ElementNode && n.Data == "title" && n.FirstChild != nil {
			return strings.TrimSpace(n.FirstChild.Data)
		}
		for child := n.FirstChild; child != nil; child = child.NextSibling {
			if value := walk(child); value != "" {
				return value
			}
		}
		return ""
	}
	return walk(root)
}

func extractText(root *html.Node) string {
	var chunks []string
	var walk func(*html.Node, bool)
	walk = func(n *html.Node, blocked bool) {
		if n.Type == html.ElementNode {
			switch n.Data {
			case "script", "style", "noscript", "svg", "nav", "footer", "form", "aside":
				blocked = true
			}
		}
		if n.Type == html.TextNode && !blocked {
			value := strings.TrimSpace(strings.Map(func(r rune) rune {
				if unicode.IsSpace(r) {
					return ' '
				}
				return r
			}, n.Data))
			if len(value) > 1 {
				chunks = append(chunks, value)
			}
		}
		for child := n.FirstChild; child != nil; child = child.NextSibling {
			walk(child, blocked)
		}
	}
	walk(root, false)
	return strings.Join(chunks, "\n")
}

type HTTPError struct{ StatusCode int }

func (e *HTTPError) Error() string { return fmt.Sprintf("page HTTP %d", e.StatusCode) }
func (e *HTTPError) Transient() bool {
	return e.StatusCode == 408 || e.StatusCode == 429 || e.StatusCode >= 500
}
