// Preserve the server's BOM: Response.text() strips it and Excel can misread UTF-8.
export async function readCsvDownload(response: Response): Promise<{ fileName: string; blob: Blob }> {
  const match = /filename="([^"]+)"/.exec(response.headers.get('content-disposition') ?? '')
  return { fileName: match?.[1] ?? 'export.csv', blob: await response.blob() }
}
