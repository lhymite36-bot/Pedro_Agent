// NOT DEPLOYED - template for real (live) payments later.
// Supabase Edge Function: verifies a Razorpay payment signature on the server and writes a 'live'
// entitlement row. Secrets live only in Supabase function secrets:
//   supabase secrets set RAZORPAY_KEY_SECRET=... (the service role key is provided by Supabase itself)
import { createClient } from "npm:@supabase/supabase-js@2";

const enc = new TextEncoder();
async function hmac(secret: string, msg: string) {
  const k = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, enc.encode(msg));
  return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req) => {
  const auth = req.headers.get("Authorization") ?? "";
  const url = Deno.env.get("SUPABASE_URL")!;
  const user = await createClient(url, Deno.env.get("SUPABASE_ANON_KEY")!, { global: { headers: { Authorization: auth } } }).auth.getUser();
  if (!user.data.user) return new Response(JSON.stringify({ ok: false, error: "Sign in first." }), { status: 401 });
  const { razorpay_order_id, razorpay_payment_id, razorpay_signature, period } = await req.json();
  const good = await hmac(Deno.env.get("RAZORPAY_KEY_SECRET")!, `${razorpay_order_id}|${razorpay_payment_id}`);
  if (good !== razorpay_signature) return new Response(JSON.stringify({ ok: false, error: "Bad signature." }), { status: 400 });
  const days = period === "year" ? 366 : 31;
  const admin = createClient(url, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  await admin.from("pb_entitlements").upsert({
    user_id: user.data.user.id, plan: "pro", period, source: "live", mode: "live", payment_id: razorpay_payment_id,
    valid_until: new Date(Date.now() + days * 86400e3).toISOString(), updated_at: new Date().toISOString(),
  });
  return new Response(JSON.stringify({ ok: true }));
});
