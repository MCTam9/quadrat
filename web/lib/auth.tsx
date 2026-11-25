"use client";

import { createContext, useContext } from "react";
import type { TokenGetter } from "./api";


export const TokenContext = createContext<TokenGetter>(async () => null);
export const useTokenGetter = () => useContext(TokenContext);
