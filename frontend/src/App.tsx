import { useState } from "react";
import Home from "./pages/Home";
import Studio from "./pages/Studio";
import Editor from "./pages/Editor";
import SettingsPage from "./pages/SettingsPage";
import NewProjectWizard from "./components/create/NewProjectWizard";
import QuickProjectCreate from "./components/create/QuickProjectCreate";

type StudioMode = "full_auto" | "co_creation";

type View =
  | { kind: "home" }
  | { kind: "quick-create"; mode: StudioMode }
  | { kind: "wizard" }
  | { kind: "settings" }
  | { kind: "studio"; projectId: string; mode: StudioMode }
  | { kind: "editor"; projectId: string };

/**
 * Kairo is one app: production, manual editing, settings, models and
 * diagnostics all live behind this single view switch rather than in a
 * separate admin area (design doc section 49).
 *
 * The three ways in from Home map onto two screens - Studio (Full Auto and
 * Co-Creation, which are the same production with the chat open or closed)
 * and Editor (manual). Either can hand off to the other at any point, so
 * AI-generated and hand-edited work compose instead of forking.
 */
export default function App() {
  const [view, setView] = useState<View>({ kind: "home" });

  if (view.kind === "studio") {
    return (
      <Studio
        projectId={view.projectId}
        mode={view.mode}
        onBack={() => setView({ kind: "home" })}
        onOpenEditor={() => setView({ kind: "editor", projectId: view.projectId })}
        onOpenSettings={() => setView({ kind: "settings" })}
      />
    );
  }

  if (view.kind === "editor") {
    return (
      <Editor
        projectId={view.projectId}
        onBack={() => setView({ kind: "home" })}
        onOpenSettings={() => setView({ kind: "settings" })}
        onOpenStudio={() =>
          setView({ kind: "studio", projectId: view.projectId, mode: "co_creation" })
        }
      />
    );
  }

  if (view.kind === "settings") {
    return <SettingsPage onClose={() => setView({ kind: "home" })} />;
  }

  if (view.kind === "quick-create") {
    // Full Auto and Co-Creation only need a project to exist; everything
    // else about the video is decided from the one instruction on the
    // studio launcher, so asking a multi-step wizard first would be the
    // "不要な質問" section 1 rules out.
    return (
      <QuickProjectCreate
        mode={view.mode}
        onCreated={(projectId) =>
          setView({ kind: "studio", projectId, mode: view.mode })
        }
        onCancel={() => setView({ kind: "home" })}
      />
    );
  }

  if (view.kind === "wizard") {
    return (
      <NewProjectWizard
        onCreated={(projectId) => setView({ kind: "editor", projectId })}
        onCancel={() => setView({ kind: "home" })}
        onOpenSettings={() => setView({ kind: "settings" })}
      />
    );
  }

  return (
    <Home
      onCreate={(mode) =>
        mode === "manual"
          ? setView({ kind: "wizard" })
          : setView({ kind: "quick-create", mode })
      }
      onOpenProject={(projectId, mode) =>
        mode === "manual"
          ? setView({ kind: "editor", projectId })
          : setView({ kind: "studio", projectId, mode })
      }
      onOpenSettings={() => setView({ kind: "settings" })}
    />
  );
}
