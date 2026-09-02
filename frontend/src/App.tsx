import { useState } from "react";
import ProjectList from "./pages/ProjectList";
import Editor from "./pages/Editor";
import SettingsPage from "./pages/SettingsPage";
import NewProjectWizard from "./components/create/NewProjectWizard";
import WelcomeIntro, { hasSeenIntro } from "./components/create/WelcomeIntro";

type View = { kind: "list" } | { kind: "wizard" } | { kind: "settings" } | { kind: "editor"; projectId: string };

export default function App() {
  const [view, setView] = useState<View>({ kind: "list" });
  const [showIntro, setShowIntro] = useState(!hasSeenIntro());

  if (view.kind === "editor") {
    return (
      <Editor
        projectId={view.projectId}
        onBack={() => setView({ kind: "list" })}
        onOpenSettings={() => setView({ kind: "settings" })}
      />
    );
  }

  if (view.kind === "settings") {
    return <SettingsPage onClose={() => setView({ kind: "list" })} />;
  }

  if (view.kind === "wizard") {
    if (showIntro) {
      return <WelcomeIntro onStart={() => setShowIntro(false)} />;
    }
    return (
      <NewProjectWizard
        onCreated={(projectId) => setView({ kind: "editor", projectId })}
        onCancel={() => setView({ kind: "list" })}
        onOpenSettings={() => setView({ kind: "settings" })}
      />
    );
  }

  return (
    <ProjectList
      onOpen={(projectId) => setView({ kind: "editor", projectId })}
      onCreateNew={() => setView({ kind: "wizard" })}
      onOpenSettings={() => setView({ kind: "settings" })}
    />
  );
}
