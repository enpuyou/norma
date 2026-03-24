"use client";

import { useContext } from "react";
import { ModeContext } from "@/app/providers";

export function useMode() {
  return useContext(ModeContext);
}
