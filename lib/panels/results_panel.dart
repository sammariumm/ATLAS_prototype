import 'dart:io';
import 'package:flutter/material.dart';
import '../services/backend_service.dart';

class ResultsPanel extends StatefulWidget {
  final List<Map<String, dynamic>> scanData;
  final String? scanId;
  final Map<String, String>? ccResult;  // CHANGED
  final Map<String, String>? mloResult; // CHANGED
  final Map<String, String>? combinedResult;
  final VoidCallback onNewPatient; 

  const ResultsPanel({
    super.key, 
    required this.scanData, 
    this.scanId, 
    this.ccResult,   // CHANGED
    this.mloResult,  // CHANGED
    this.combinedResult,
    required this.onNewPatient, 
  });

  @override
  State<ResultsPanel> createState() => _ResultsPanelState();
}

class _ResultsPanelState extends State<ResultsPanel> {
  bool? _isAccurate;
  bool _isSubmitting = false;

  void _showEnlargedImage(String path) {
    if (path.isEmpty) return;
    showDialog(
      context: context,
      builder: (context) => Dialog(
        backgroundColor: Colors.black,
        insetPadding: EdgeInsets.zero,
        child: Stack(
          alignment: Alignment.topRight,
          children: [
            SizedBox(width: double.infinity, height: double.infinity, child: Image.file(File(path), fit: BoxFit.contain)),
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: Colors.red, padding: const EdgeInsets.all(16)),
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('CLOSE', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _handleSubmit() async {
    if (_isAccurate == null || widget.scanData.length < 2 || widget.scanId == null) return;
    setState(() => _isSubmitting = true);

    try {
      await BackendService.saveScanRecord(
        scanId: widget.scanId!,
        scanData: widget.scanData,
        ccResult: widget.ccResult,
        mloResult: widget.mloResult,
        combinedResult: widget.combinedResult,
        isAccurate: _isAccurate!,
      );
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Saved to Database!'), backgroundColor: Color(0xFF0D9488)));
      
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Database Error'), backgroundColor: Colors.red));
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          flex: 4,
          child: Container(
            color: const Color(0xFF1E293B),
            padding: const EdgeInsets.all(8),
            child: Row(
              children: widget.scanData.map((scan) => Expanded(
                child: GestureDetector(
                  onTap: () => _showEnlargedImage(scan['image_path']),
                  child: Container(
                    margin: const EdgeInsets.symmetric(horizontal: 4),
                    decoration: BoxDecoration(color: Colors.black, border: Border.all(color: Colors.grey.shade800), borderRadius: BorderRadius.circular(8)),
                    child: Stack(
                      fit: StackFit.expand,
                      children: [
                        Image.file(File(scan['image_path']), fit: BoxFit.cover),
                        Positioned(
                          bottom: 8, left: 8,
                          child: Container(padding: const EdgeInsets.all(4), color: Colors.black87, child: Text('${scan['side']} ${scan['view']}', style: const TextStyle(color: Colors.white, fontSize: 12))),
                        )
                      ],
                    ),
                  ),
                ),
              )).toList(),
            ),
          ),
        ),
        Expanded(
          flex: 6,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('COMBINED AI RESULT', style: TextStyle(color: Color(0xFF64748B), fontWeight: FontWeight.bold, fontSize: 14)),
                const SizedBox(height: 8),
                Text(widget.combinedResult?['classification'] ?? '--', style: const TextStyle(color: Color(0xFF0F172A), fontSize: 32, fontWeight: FontWeight.bold)),
                Text('Confidence: ${widget.combinedResult?['confidence'] ?? '--'}', style: const TextStyle(color: Color(0xFF0D9488), fontSize: 18, fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                Text(widget.combinedResult?['recommendation'] ?? 'Awaiting Data...', style: const TextStyle(fontSize: 16, color: Color(0xFF0F172A))),
                const Divider(height: 24),
                Row(
                  children: [
                    Expanded(
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _isAccurate == true ? const Color(0xFF0D9488) : Colors.white, side: const BorderSide(color: Color(0xFF0D9488)), padding: const EdgeInsets.symmetric(vertical: 16)),
                        onPressed: widget.scanData.length < 2 ? null : () => setState(() => _isAccurate = true),
                        child: Text('Accurate', textAlign: TextAlign.center, style: TextStyle(color: _isAccurate == true ? Colors.white : const Color(0xFF0D9488), fontSize: 16)),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _isAccurate == false ? const Color(0xFFE11D48) : Colors.white, side: const BorderSide(color: Color(0xFFE11D48)), padding: const EdgeInsets.symmetric(vertical: 16)),
                        onPressed: widget.scanData.length < 2 ? null : () => setState(() => _isAccurate = false),
                        child: Text('Inaccurate', textAlign: TextAlign.center, style: TextStyle(color: _isAccurate == false ? Colors.white : const Color(0xFFE11D48), fontSize: 16)),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0F172A), padding: const EdgeInsets.symmetric(vertical: 16)),
                  onPressed: (_isAccurate == null || _isSubmitting || widget.scanData.length < 2) ? null : _handleSubmit,
                  child: _isSubmitting ? const CircularProgressIndicator(color: Colors.white) : const Text('SUBMIT VALIDATION', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                ),
                const SizedBox(height: 12),
                
                TextButton.icon(
                  style: TextButton.styleFrom(foregroundColor: Colors.red, padding: const EdgeInsets.symmetric(vertical: 16)),
                  onPressed: widget.onNewPatient, // Triggers global reset
                  icon: const Icon(Icons.delete_forever),
                  label: const Text('DISCARD SCAN & RESTART', style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
                )
              ],
            ),
          ),
        ),
      ],
    );
  }
}