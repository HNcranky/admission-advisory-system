Có thể crawl được, nhưng với trang này có một điểm cần lưu ý:

Trang HTML tĩnh mình đọc được **đang expose trực tiếp dữ liệu năm 2025**, gồm section `Điểm chuẩn theo phương thức Điểm thi THPT năm 2025` và các dòng ngành/điểm chuẩn phía dưới. Ví dụ: `Kỹ thuật Thực phẩm (CT tiên tiến) ... 21`, `Kỹ thuật Sinh học ... 23.02`, `CNTT: Khoa học Máy tính ... 29.19`… ([Điểm thi - Tuyển sinh 247][1])

Tuy nhiên các năm cũ như **2024** trên trang chỉ hiện dạng link/text “Xem thêm điểm chuẩn theo phương thức Điểm thi THPT năm 2024”, không thấy dữ liệu 2024–2022 được render sẵn trong HTML mà công cụ đọc được. ([Điểm thi - Tuyển sinh 247][1]) Nghĩa là nếu crawl bằng `requests + BeautifulSoup` đơn thuần thì nhiều khả năng chỉ lấy được 2025; muốn lấy 2024–2022 cần dùng **browser automation** như Playwright/Selenium để click “Xem thêm…” hoặc inspect API mà trang gọi ngầm.

Cách crawl hợp lý:

```ts
import { chromium } from "playwright";

const url =
  "https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html";

const years = [2025, 2024, 2023, 2022];

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  await page.goto(url, { waitUntil: "networkidle" });

  const results: any[] = [];

  for (const year of years) {
    // Nếu năm cũ chưa render, thử click link "Xem thêm..."
    const moreText = `Xem thêm điểm chuẩn theo phương thức Điểm thi THPT năm ${year}`;
    const more = page.getByText(moreText, { exact: false });

    if (year !== 2025 && (await more.count()) > 0) {
      await more.first().click();
      await page.waitForLoadState("networkidle").catch(() => {});
      await page.waitForTimeout(1000);
    }

    const sectionTitle = `Điểm chuẩn theo phương thức Điểm thi THPT năm ${year}`;

    const rows = await page.evaluate((sectionTitle) => {
      const text = document.body.innerText;
      const start = text.indexOf(sectionTitle);
      if (start === -1) return [];

      const rest = text.slice(start);
      const nextSection = rest.search(
        /\n\s*Điểm chuẩn theo phương thức|\n\s*Xem thêm điểm chuẩn theo phương thức/
      );

      const block = nextSection > 0 ? rest.slice(0, nextSection) : rest;

      return block
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .filter(
          (line) =>
            !line.includes("Tên ngành") &&
            !line.includes("Tra cứu tại") &&
            !line.includes("Điểm chuẩn theo phương thức")
        );
    }, sectionTitle);

    for (const row of rows) {
      results.push({
        school_code: "BKA",
        school_name: "Đại học Bách khoa Hà Nội",
        year,
        method: "Điểm thi THPT",
        raw_text: row,
      });
    }
  }

  console.log(JSON.stringify(results, null, 2));

  await browser.close();
}

main();
```

Nếu muốn parse sạch hơn, mình khuyên lưu trước dạng `raw_text`, sau đó normalize thành schema:

```ts
{
  year: 2025,
  school_code: "BKA",
  method: "Điểm thi THPT",
  major_name: "CNTT: Khoa học Máy tính",
  subject_combination: "A00; A01",
  cutoff_score: 29.19,
  note: "Môn chính: Toán"
}
```

Kết luận: **crawl được**, nhưng nên dùng **Playwright** thay vì chỉ `requests`, vì các năm 2024–2022 có vẻ được load/ẩn động sau thao tác “Xem thêm”, còn HTML tĩnh hiện tại chỉ cho thấy rõ bảng 2025 và link xem thêm năm 2024.

[1]: https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html "Điểm chuẩn Đại Học Bách Khoa Hà Nội 2025 chính xác"
