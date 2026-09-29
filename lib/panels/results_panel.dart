import 'dart:io';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import '../services/backend_service.dart';

/// Shows bilateral thumbnails, combined AI output, and physician validation.
class ResultsPanel extends StatefulWidget {
  final List<Map<String, dynamic>> scanData;
  final String? scanId;
  final Map<String, String>? combinedResult;
  final bool isProcessing;

  const ResultsPanel({
    super.key,
    required this.scanData,
    this.scanId,
    this.combinedResult,
    this.isProcessing = false,
  });

  @override
  State<ResultsPanel> createState() => _ResultsPanelState();
}

class _ResultsPanelState extends State<ResultsPanel> {
  bool? _isAccurate;
  bool _isSubmitting = false;

  String _imagePath(Map<String, dynamic> scan) {
    return scan['image_path'] as String? ?? '';
  }

  void _showEnlargedImage(String path) {
    if (path.isEmpty) return;
    showDialog(
      context: context,
      builder: (context) => Dialog(
        backgroundColor: Colors.black,
        insetPadding: const EdgeInsets.all(16),
        child: Stack(
          alignment: Alignment.topRight,
          children: [
            InteractiveViewer(
              panEnabled: true, minScale: 1.0, maxScale: 4.0,
              child: SizedBox(width: double.infinity, height: double.infinity, child: kIsWeb ? Image.network(path, fit: BoxFit.contain) : Image.file(File(path), fit: BoxFit.contain)),
            ),
            IconButton(icon: const Icon(Icons.close, color: Colors.white, size: 32), onPressed: () => Navigator.of(context).pop()),
          ],
        ),
      ),
    );
  }

  Future<void> _handleSubmit() async {
    if (_isAccurate == null || widget.scanData.length < 2 || widget.scanId == null) return;
    setState(() => _isSubmitting = true);

    try {
      if (_isAccurate == true) {
        await BackendService.sendToBlockchain(
          scanId: widget.scanId!,
          scanData: widget.scanData,
          combinedClassification: widget.combinedResult?['classification'] ?? 'Unknown',
          isAccurate: _isAccurate!,
        );
      }
      await BackendService.saveToDatabase(scanId: widget.scanId!, physicianName: 'Doctor', email: null);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Combined Result submitted!'), backgroundColor: Color(0xFF0D9488)));
    } catch (e) {
      debugPrint('$e');
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('Captured Scans (Bilateral)', style: TextStyle(fontWeight: FontWeight.bold, color: Color(0xFF64748B))),
          const SizedBox(height: 8),
          
          SizedBox(
            height: 160,
            child: Row(
              children: [
                for (int i = 0; i < 2; i++)
                  Expanded(
                    child: Padding(
                      padding: EdgeInsets.only(right: i == 0 ? 8.0 : 0.0),
                      child: GestureDetector(
                        onTap: (i < widget.scanData.length && _imagePath(widget.scanData[i]).isNotEmpty) ? () => _showEnlargedImage(_imagePath(widget.scanData[i])) : null,
                        child: Container(
                          decoration: BoxDecoration(color: Colors.black, borderRadius: BorderRadius.circular(8)),
                          clipBehavior: Clip.antiAlias,
                          child: Stack(
                            fit: StackFit.expand,
                            children: [
                              (i < widget.scanData.length && _imagePath(widget.scanData[i]).isNotEmpty)
                                  ? (kIsWeb ? Image.network(_imagePath(widget.scanData[i]), fit: BoxFit.cover) : Image.file(File(_imagePath(widget.scanData[i])), fit: BoxFit.cover))
                                  : Center(child: Text(i < widget.scanData.length ? 'Mock Image' : 'Pending', style: const TextStyle(color: Colors.white54, fontSize: 12))),
                              if (i < widget.scanData.length)
                                Positioned(
                                  bottom: 4, left: 4,
                                  child: Container(padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2), color: Colors.black87, child: Text('${widget.scanData[i]['side']} (${widget.scanData[i]['view']})', style: const TextStyle(color: Colors.white, fontSize: 10))),
                                ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 16),

          Card(
            elevation: 0, color: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: const BorderSide(color: Color(0xFFE2E8F0))),
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: widget.isProcessing
                  ? const Padding(
                      padding: EdgeInsets.all(24.0),
                      child: Center(child: Column(children: [CircularProgressIndicator(color: Color(0xFF0D9488)), SizedBox(height: 16), Text('Analyzing Bilateral Scans...', style: TextStyle(color: Color(0xFF64748B)))])))
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('COMBINED AI ANALYSIS RESULT', style: TextStyle(color: Color(0xFF94A3B8), fontWeight: FontWeight.bold, fontSize: 12)),
                        const SizedBox(height: 12),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text('Classification', style: TextStyle(color: Color(0xFF64748B), fontSize: 14)),
                                Text(widget.combinedResult?['classification'] ?? '--', style: const TextStyle(color: Color(0xFF0F172A), fontSize: 24, fontWeight: FontWeight.bold)),
                              ],
                            ),
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                const Text('Confidence', style: TextStyle(color: Color(0xFF64748B), fontSize: 14)),
                                Text(widget.combinedResult?['confidence'] ?? '--', style: const TextStyle(color: Color(0xFF0D9488), fontSize: 24, fontWeight: FontWeight.bold)),
                              ],
                            ),
                          ],
                        ),
                        const Divider(height: 24),
                        const Text('Next Step Recommendation', style: TextStyle(color: Color(0xFF64748B), fontSize: 12)),
                        const SizedBox(height: 4),
                        Text(widget.combinedResult?['recommendation'] ?? 'N/A', style: const TextStyle(fontSize: 16, color: Color(0xFF0F172A))),
                      ],
                    ),
            ),
          ),
          const SizedBox(height: 16),

          Row(
            children: [
              Expanded(
                child: GestureDetector(
                  onTap: (widget.isProcessing || widget.scanData.length < 2) ? null : () => setState(() => _isAccurate = true),
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    decoration: BoxDecoration(color: _isAccurate == true ? const Color(0xFFE6FFFA) : Colors.white, border: Border.all(color: _isAccurate == true ? const Color(0xFF0D9488) : const Color(0xFFE2E8F0), width: 2), borderRadius: BorderRadius.circular(8)),
                    child: Column(children: const [Text('Accurate', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Color(0xFF0F172A))), Text('Send to Blockchain', style: TextStyle(color: Color(0xFF0D9488), fontSize: 10))]),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: GestureDetector(
                  onTap: (widget.isProcessing || widget.scanData.length < 2) ? null : () => setState(() => _isAccurate = false),
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    decoration: BoxDecoration(color: _isAccurate == false ? const Color(0xFFFFF1F2) : Colors.white, border: Border.all(color: _isAccurate == false ? const Color(0xFFE11D48) : const Color(0xFFE2E8F0), width: 2), borderRadius: BorderRadius.circular(8)),
                    child: Column(children: const [Text('Inaccurate', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Color(0xFF0F172A))), Text('Discard Result', style: TextStyle(color: Color(0xFFE11D48), fontSize: 10))]),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0F172A), padding: const EdgeInsets.symmetric(vertical: 16), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
            onPressed: (_isAccurate == null || widget.isProcessing || widget.scanData.length < 2 || _isSubmitting) ? null : _handleSubmit,
            child: _isSubmitting ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)) : const Text('Submit Selection', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
          )
        ],
      ),
    );
  }
}