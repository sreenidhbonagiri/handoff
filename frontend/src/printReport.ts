async function waitForImages(doc: Document): Promise<void> {
  await Promise.all(
    [...doc.images].map((img) => {
      if (typeof img.decode === "function") return img.decode().catch(() => undefined);
      if (img.complete) return Promise.resolve();
      return new Promise<void>((resolve) => {
        img.onload = () => resolve();
        img.onerror = () => resolve();
      });
    }),
  );
}

function prepareReportDocument(doc: Document): void {
  for (const details of doc.querySelectorAll("details")) details.open = true;
}

export async function printReport(url: string): Promise<void> {
  const frame = document.createElement("iframe");
  frame.className = "print-frame";
  frame.title = "Print report";
  frame.setAttribute("aria-hidden", "true");
  document.body.appendChild(frame);

  const loaded = new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("The report took too long to load.")), 20000);
    frame.onload = () => {
      window.clearTimeout(timer);
      resolve();
    };
    frame.onerror = () => {
      window.clearTimeout(timer);
      reject(new Error("Could not load the report."));
    };
  });
  const sep = url.includes("?") ? "&" : "?";
  frame.src = `${url}${sep}t=${Date.now()}`;
  try {
    await loaded;
    const doc = frame.contentDocument;
    const win = frame.contentWindow;
    if (!doc || !win) throw new Error("Could not open the report.");
    prepareReportDocument(doc);
    await waitForImages(doc);
    win.focus();
    win.print();
  } finally {
    window.setTimeout(() => frame.remove(), 60_000);
  }
}
