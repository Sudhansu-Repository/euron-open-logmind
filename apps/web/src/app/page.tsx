import { redirect } from "next/navigation";

/** The overview is the front door; the middleware sends signed-out visitors to sign in. */
export default function Home() {
  redirect("/overview");
}
