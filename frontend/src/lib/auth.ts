/**
 * AWS Amplify / Cognito authentication helpers.
 * Wraps Amplify v6 API for use across the Next.js admin UI.
 */

import { Amplify } from "aws-amplify";
import {
  signIn,
  signOut,
  getCurrentUser,
  fetchAuthSession,
  type AuthUser,
} from "aws-amplify/auth";

// Configure Amplify once (called from app/layout.tsx or a client component)
export function configureAmplify() {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID!,
        userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID!,
        loginWith: {
          email: true,
        },
      },
    },
  });
}

export async function login(email: string, password: string) {
  try {
    return await signIn({
      username: email,
      password,
      options: { authFlowType: "USER_SRP_AUTH" },
    });
  } catch (err: unknown) {
    // Amplify v6 throws this when a previous sign-in is still cached
    if (err instanceof Error && err.name === "UserAlreadyAuthenticatedException") {
      await signOut();
      return await signIn({
        username: email,
        password,
        options: { authFlowType: "USER_SRP_AUTH" },
      });
    }
    throw err;
  }
}

export async function logout() {
  await signOut();
}

export async function getAuthenticatedUser(): Promise<AuthUser | null> {
  try {
    return await getCurrentUser();
  } catch {
    return null;
  }
}

export async function getIdToken(): Promise<string | null> {
  try {
    const session = await fetchAuthSession();
    return session.tokens?.idToken?.toString() ?? null;
  } catch {
    return null;
  }
}

export async function getUserGroups(): Promise<string[]> {
  try {
    const session = await fetchAuthSession();
    const payload = session.tokens?.idToken?.payload;
    const groups = payload?.["cognito:groups"];
    return Array.isArray(groups) ? (groups as string[]) : [];
  } catch {
    return [];
  }
}

export async function isAdmin(): Promise<boolean> {
  const groups = await getUserGroups();
  return groups.includes("Admin");
}
