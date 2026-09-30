import 'dart:io';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import '../services/backend_service.dart';

class ExportPanel extends StatefulWidget {
  final List<Map<String, dynamic>> scanData;
  final String? scanId;
  final Map<String, String>? ccResult;   // CHANGED
  final Map<String, String>? mloResult;  // CHANGED
  final Map<String, String>? combinedResult;
  final VoidCallback onNewPatient; 

  const ExportPanel({
    super.key,
    required this.scanData,
    this.scanId,
    this.ccResult,  // CHANGED
    this.mloResult, // CHANGED
    this.combinedResult,
    required this.onNewPatient, 
  });

  @override
  State<ExportPanel> createState() => _ExportPanelState();
}

class _ExportPanelState extends State<ExportPanel> {
  final TextEditingController _emailController = TextEditingController();
  bool _isGeneratingPDF = false;
  bool _isSendingEmail = false;
  String? _savedPdfPath;

  Future<void> _generatePDF() async {
    if (widget.scanData.length < 2 || widget.scanId == null) return;
    setState(() => _isGeneratingPDF = true);

    try {
      final pdf = pw.Document();

      // 1. SAFELY search for the CC and MLO images
      String? ccImagePath;
      String? mloImagePath;
      String? scannedSide; // To determine if this is a Left or Right breast report
      
      for (var scan in widget.scanData) {
        if (scan['view'] == 'CC') {
          ccImagePath = scan['image_path'];
          scannedSide = scan['side']; // Capture which side this is for the PDF title
        }
        if (scan['view'] == 'MLO') mloImagePath = scan['image_path'];
      }

      if (ccImagePath == null || mloImagePath == null) {
        throw Exception('Missing CC or MLO scan. Please capture both views.');
      }

      final ccImageFile = File(ccImagePath);
      final mloImageFile = File(mloImagePath);
      
      final ccImage = pw.MemoryImage(ccImageFile.readAsBytesSync());
      final mloImage = pw.MemoryImage(mloImageFile.readAsBytesSync());

      pdf.addPage(
        pw.MultiPage(
          pageFormat: PdfPageFormat.a4,
          build: (context) => [
            pw.Header(level: 0, child: pw.Text('ATLAS-BC: Mammography Analysis', style: pw.TextStyle(fontSize: 24, fontWeight: pw.FontWeight.bold))),
            pw.Text('Scan ID: ${widget.scanId} | Date: ${DateTime.now().toString().split('.')[0]}'),
            pw.SizedBox(height: 20),
            
            pw.Container(
              padding: const pw.EdgeInsets.all(12),
              color: PdfColors.grey200,
              child: pw.Column(
                crossAxisAlignment: pw.CrossAxisAlignment.start,
                children: [
                  pw.Text('OVERALL UNILATERAL DIAGNOSIS: ${scannedSide?.toUpperCase() ?? ''} BREAST', style: pw.TextStyle(fontSize: 14, fontWeight: pw.FontWeight.bold)),
                  pw.SizedBox(height: 8),
                  pw.Text('Classification: ${widget.combinedResult?['classification'] ?? 'N/A'}', style: pw.TextStyle(fontSize: 22, color: PdfColors.red800, fontWeight: pw.FontWeight.bold)),
                  pw.Text('Confidence: ${widget.combinedResult?['confidence'] ?? 'N/A'}'),
                ]
              )
            ),
            pw.SizedBox(height: 20),

            pw.Text('Individual Views', style: pw.TextStyle(fontSize: 18, fontWeight: pw.FontWeight.bold)),
            pw.Divider(),
            pw.Row(
              mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
              crossAxisAlignment: pw.CrossAxisAlignment.start,
              children: [
                pw.Expanded(
                  child: pw.Column(
                    crossAxisAlignment: pw.CrossAxisAlignment.start,
                    children: [
                      pw.Text('CC VIEW', style: pw.TextStyle(fontWeight: pw.FontWeight.bold)),
                      pw.Text('Result: ${widget.ccResult?['classification'] ?? 'N/A'}'),
                      pw.Text('Confidence: ${widget.ccResult?['confidence'] ?? 'N/A'}'),
                      pw.SizedBox(height: 10),
                      pw.Image(ccImage, height: 200)
                    ]
                  )
                ),
                pw.SizedBox(width: 20),
                pw.Expanded(
                  child: pw.Column(
                    crossAxisAlignment: pw.CrossAxisAlignment.start,
                    children: [
                      pw.Text('MLO VIEW', style: pw.TextStyle(fontWeight: pw.FontWeight.bold)),
                      pw.Text('Result: ${widget.mloResult?['classification'] ?? 'N/A'}'),
                      pw.Text('Confidence: ${widget.mloResult?['confidence'] ?? 'N/A'}'),
                      pw.SizedBox(height: 10),
                      pw.Image(mloImage, height: 200)
                    ]
                  )
                ),
              ]
            ),
            pw.SizedBox(height: 30),

            pw.Text('Patient Next Steps', style: pw.TextStyle(fontSize: 18, fontWeight: pw.FontWeight.bold)),
            pw.Divider(),
            pw.Text(widget.combinedResult?['recommendation'] ?? 'Consult healthcare provider for further evaluation.', style: const pw.TextStyle(fontSize: 14)),
          ],
        ),
      );

      final outputDir = await getApplicationDocumentsDirectory();
      final file = File('${outputDir.path}/ATLAS_${widget.scanId}.pdf');
      await file.writeAsBytes(await pdf.save());

      setState(() => _savedPdfPath = file.path);

      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('PDF Saved: ${file.path}'), backgroundColor: const Color(0xFF0D9488)));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red));
    } finally {
      if (mounted) setState(() => _isGeneratingPDF = false);
    }
  }

  Future<void> _sendEmail() async {
    if (_emailController.text.isEmpty || _savedPdfPath == null) return;
    setState(() => _isSendingEmail = true);

    try {
      await BackendService.sendEmailReport(emailAddress: _emailController.text, pdfFilePath: _savedPdfPath!, scanId: widget.scanId!);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Email Sent Successfully!'), backgroundColor: Color(0xFF0D9488)));
        _emailController.clear();
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red));
    } finally {
      if (mounted) setState(() => _isSendingEmail = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bool canGenerate = widget.scanData.length >= 2 && widget.scanId != null;

    return Padding(
      padding: const EdgeInsets.all(12.0),
      child: Column(
        children: [
          Expanded(
            flex: 4,
            child: Container(
              padding: const EdgeInsets.all(16.0),
              decoration: BoxDecoration(color: const Color(0xFF1E293B), borderRadius: BorderRadius.circular(12)),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.picture_as_pdf, size: 40, color: Colors.white),
                  const SizedBox(height: 8),
                  Text('Report: ${widget.scanId ?? 'Pending'}', textAlign: TextAlign.center, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Text(_savedPdfPath != null ? 'PDF Generated' : 'Data Ready', textAlign: TextAlign.center, style: TextStyle(color: _savedPdfPath != null ? const Color(0xFF0D9488) : Colors.white54, fontSize: 14)),
                  const Spacer(),
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0D9488), padding: const EdgeInsets.symmetric(vertical: 16)),
                    onPressed: (canGenerate && !_isGeneratingPDF) ? _generatePDF : null,
                    icon: _isGeneratingPDF ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white)) : const Icon(Icons.download, color: Colors.white, size: 20),
                    label: const Text('GENERATE PDF', style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold)),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Expanded(
            flex: 4,
            child: Container(
              padding: const EdgeInsets.all(16.0),
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.grey.shade300)),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('Email Report', style: TextStyle(color: Color(0xFF0F172A), fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _emailController,
                    keyboardType: TextInputType.emailAddress,
                    style: const TextStyle(fontSize: 14),
                    decoration: InputDecoration(
                      labelText: 'Email Address',
                      labelStyle: const TextStyle(fontSize: 14),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                      prefixIcon: const Icon(Icons.email, size: 20),
                      contentPadding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                  const Spacer(),
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0F172A), padding: const EdgeInsets.symmetric(vertical: 16)),
                    onPressed: (_savedPdfPath != null && !_isSendingEmail) ? _sendEmail : null,
                    icon: _isSendingEmail ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white)) : const Icon(Icons.send, color: Colors.white, size: 20),
                    label: const Text('SEND EMAIL', style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold)),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          
          // NEW: BIG Reset Button at the bottom
          ElevatedButton.icon(
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.amber.shade700,
              padding: const EdgeInsets.symmetric(vertical: 24),
              minimumSize: const Size(double.infinity, 60),
            ),
            onPressed: widget.onNewPatient, // Triggers global reset
            icon: const Icon(Icons.person_add, color: Colors.black, size: 24),
            label: const Text('FINISH & START NEW PATIENT', style: TextStyle(color: Colors.black, fontSize: 16, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }
}