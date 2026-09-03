<div align="center">
<img src="../images/banner1-en.svg" alt="xiaozhi-fde-talk" width="100%" />

# Xiaozhi FDE Talk

### Không chỉ chuyển giọng nói thành văn bản—mà là trợ lý phỏng vấn AI biết lắng nghe và gợi ý

**Dành cho người thường xuyên phỏng vấn khách hàng**: FDE, quản lý sản phẩm, pre-sales, tư vấn viên…

Các công cụ ghi âm thông thường chỉ giúp bạn tổng hợp sau buổi phỏng vấn. Công cụ này lắng nghe theo thời gian thực và gợi ý bạn nên hỏi gì tiếp theo, những điểm nào chưa được đề cập. Khi buổi phỏng vấn kết thúc, bạn có ngay báo cáo yêu cầu có cấu trúc—không cần ghi chép thủ công.

[Bắt đầu nhanh](#quick-start) · [Tài liệu](../index.md) · [Báo lỗi](https://github.com/xinnan-tech/xiaozhi-fde-talk/issues)

[![中文](https://img.shields.io/badge/%E4%B8%AD%E6%96%87-zh--CN-lightgrey.svg)](../../README.md)
[![English](https://img.shields.io/badge/English-en--US-lightgrey.svg)](README.en-US.md)
[![Tiếng Việt](https://img.shields.io/badge/Ti%E1%BA%BFng%20Vi%E1%BB%87t-current-green.svg)](README.vi-VN.md)

</div>

## ✨ Nó làm được gì

- 🤖 **Bảo bạn nên hỏi gì, theo thời gian thực**: vừa nghe vừa phân tích, gợi ý câu hỏi tiếp theo và những điểm chưa được đề cập—người mới cũng phỏng vấn như chuyên gia
- 🎙️ **Chuyển giọng nói thành văn bản ngay khi nói**: bật mic là chạy. Văn bản chuyển ngay còn làm đầu vào cho bộ coaching. Nếu dùng FunASR local thì dữ liệu giọng nói không ra khỏi mạng nội bộ
- 📝 **Tự động ra báo cáo khi kết thúc**: không cần nghe lại ghi âm tổng hợp. Có ngay tài liệu yêu cầu có cấu trúc, xuất Markdown, HTML, hoặc Word

***

<a id="quick-start"></a>

## 🚀 Ba câu để chạy

Cần cài Docker sẵn.

```bash
git clone https://github.com/xinnan-tech/xiaozhi-fde-talk.git
cd xiaozhi-fde-talk
docker compose up -d app
```

Lần đầu sẽ tải chương trình từ internet (vài trăm MB), mất khoảng một hai phút.

Sau đó mở trình duyệt, vào [https://localhost:8848](https://localhost:8848).

> Trình duyệt sẽ báo "Kết nối của bạn không riêng tư" hoặc tương tự—đừng lo. Đó là chứng chỉ demo đi kèm repo. Bấm "Nâng cao" rồi "Tiếp tục đến localhost" là vào được.

Vào trong thì bấm "Đăng ký" để tạo tài khoản. **Người đăng ký đầu tiên sẽ làm admin**, quản lý mọi thứ.

Phỏng vấn có giọng nói cần cả mô hình AI và nhận dạng giọng nói. Không có khóa AI thì không tạo được phỏng vấn. Không có nhận dạng giọng nói thì không có transcript trực tiếp khi nói chuyện. Có thể chạy chương trình trước rồi cấu hình sau trong "Cấu hình hệ thống".

Đầy đủ tài liệu ở [đây](../index.md).

## 🚩 Hướng dẫn cấu hình và khuyến nghị
> [!Note]
> Dự án này cung cấp hai phương án cấu hình:
>
> 1. Cấu hình `miễn phí`: phù hợp cho cá nhân sử dụng, mọi thành phần đều dùng phương án miễn phí, không cần trả phí thêm.
>
> 2. Cấu hình `thương mại nâng cao`: phù hợp cho kịch bản từ 2 cuộc phỏng vấn đồng thời trở lên. Tốc độ phản hồi nhanh hơn, trải nghiệm mượt mà hơn.
>

| Mô-đun | Cấu hình miễn phí | Cấu hình thương mại nâng cao |
|:---:|:---:|:---:|
| ASR (Nhận dạng giọng nói) | FunASR Server (local streaming) | 👍 Doubao Stream ASR (Doubao streaming) |
| LLM (Mô hình ngôn ngữ lớn) | glm-4.7-flash (Zhipu) | 👍 qwen-plus (Aliyun Bailian) |
| OCR (Nhận dạng hình ảnh) | Baidu OCR (Baidu Cloud OCR có hạn mức miễn phí hàng tháng dồi dào) | 👍 Baidu OCR (Baidu Cloud OCR) |