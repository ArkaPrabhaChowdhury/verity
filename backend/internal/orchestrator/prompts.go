package orchestrator

import (
	"embed"
	"fmt"
)

//go:embed prompts/*.md
var promptFiles embed.FS

func prompt(name string) string {
	value, err := promptFiles.ReadFile("prompts/" + name + ".md")
	if err != nil {
		panic(fmt.Sprintf("required prompt %q missing: %v", name, err))
	}
	return string(value)
}
