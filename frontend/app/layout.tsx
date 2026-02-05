import "./globals.css";

export const metadata = {
  title: "OpsRelay",
  description: "Incident triage dashboard and chat interface",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="gradient-shell min-h-screen">
        {children}
      </body>
    </html>
  );
}
