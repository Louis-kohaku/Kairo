import { useState } from "react";
import ProjectList from "./pages/ProjectList";
import Editor from "./pages/Editor";

export default function App() {
  const [projectId, setProjectId] = useState<string | null>(null);

  if (projectId) {
    return <Editor projectId={projectId} onBack={() => setProjectId(null)} />;
  }
  return <ProjectList onOpen={setProjectId} />;
}
