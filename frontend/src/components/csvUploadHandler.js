export async function demoUploadHandler(file) {
  await new Promise((resolve) => setTimeout(resolve, 500))

  return {
    message: `${file.name} passed local validation only. No file was uploaded, stored, or processed.`
  }
}
