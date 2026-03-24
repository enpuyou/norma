"use client";

import { createContext, useState } from "react";
import type { ViewMode } from "@/lib/types";

interface ModeCtx {
  mode: ViewMode;
  setMode: (m: ViewMode) => void;
}

export const ModeContext = createContext<ModeCtx>({ mode: "vp", setMode: () => {} });

export function ModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<ViewMode>("vp");
  return (
    <ModeContext.Provider value={{ mode, setMode }}>
      {children}
    </ModeContext.Provider>
  );
}
